#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
催收质检 - 智能小结 API 服务

功能:
1. 接收转录文本
2. 调用 LLM 生成结构化的小结标签
3. 返回 JSON 格式的标签数据

使用方法:
    python api_server.py

依赖:
    pip install flask flask-cors requests python-dotenv
"""

import os
import sys
import traceback
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from analysis_service import (
    MODEL_NAME,
    analyze_transcript,
    generate_qc_report as build_qc_report,
    generate_summary as build_summary,
)
from audio_pipeline_service import process_audio_file
from mysql_storage import format_case_record, get_case_record, init_mysql_tables, list_case_records
from oss_utils import sign_existing_object_url

# 加载环境变量
load_dotenv()
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # ✅ 中文 JSON 不转义
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 限制上传文件最大 200MB
CORS(app)  # 允许跨域请求
init_mysql_tables()

PROJECT_ROOT = Path(__file__).parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_AUDIO_EXTENSIONS = {".m4a", ".wav", ".mp3", ".mp4"}


def is_allowed_audio_file(filename: str) -> bool:
    """校验上传文件扩展名，避免非音频文件直接进入处理链路。"""
    suffix = Path(filename).suffix.lower()
    return suffix in ALLOWED_AUDIO_EXTENSIONS


@app.route("/api/health", methods=["GET"])
def health_check():
    """健康检查"""
    return jsonify({"status": "ok", "model": MODEL_NAME})


@app.route("/api/cases", methods=["GET"])
def list_cases():
    """
    查询案件列表。

    返回值已经按前端需要的结构整理好，前端拿到后可以直接渲染。
    """
    try:
        limit = request.args.get("limit", default=100, type=int)
        rows = list_case_records(limit=limit)
        cases = []

        for row in rows:
            case_data = format_case_record(row)
            wav_object_key = case_data["storage"].get("wavAudioObjectKey")
            original_object_key = case_data["storage"].get("originalAudioObjectKey")

            # 查询列表时就刷新签名 URL，避免数据库里原来存的 URL 过期
            if wav_object_key:
                case_data["storage"]["wavAudioUrl"] = sign_existing_object_url(wav_object_key)
            if original_object_key:
                case_data["storage"]["originalAudioUrl"] = sign_existing_object_url(original_object_key)

            cases.append(case_data)

        return jsonify({"success": True, "cases": cases})
    except Exception as e:
        print(f"❌ 查询案件列表失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cases/<case_id>", methods=["GET"])
def get_case_detail(case_id):
    """查询单个案件详情。"""
    try:
        row = get_case_record(case_id)
        if not row:
            return jsonify({"success": False, "error": "案件不存在"}), 404

        case_data = format_case_record(row)
        wav_object_key = case_data["storage"].get("wavAudioObjectKey")
        original_object_key = case_data["storage"].get("originalAudioObjectKey")

        if wav_object_key:
            case_data["storage"]["wavAudioUrl"] = sign_existing_object_url(wav_object_key)
        if original_object_key:
            case_data["storage"]["originalAudioUrl"] = sign_existing_object_url(original_object_key)

        return jsonify({"success": True, "case": case_data})
    except Exception as e:
        print(f"❌ 查询案件详情失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/upload_audio", methods=["POST"])
def upload_audio():
    """
    上传音频并直接完成处理、上传 OSS、保存 MySQL。

    前端调用这个接口后，就不需要再手工把音频先放到本地目录。
    """
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "未检测到上传文件字段 file"}), 400

        upload_file = request.files["file"]
        if not upload_file or not upload_file.filename:
            return jsonify({"success": False, "error": "上传文件为空"}), 400

        if not is_allowed_audio_file(upload_file.filename):
            allowed_types = ", ".join(sorted(ALLOWED_AUDIO_EXTENSIONS))
            return jsonify({"success": False, "error": f"暂不支持该文件类型，请上传: {allowed_types}"}), 400

        safe_filename = secure_filename(upload_file.filename)
        # 如果 secure_filename 把中文清空了，就退回到时间戳文件名
        if not safe_filename:
            safe_filename = f"upload_{os.getpid()}_{Path(upload_file.filename).suffix.lower()}"

        local_upload_path = UPLOAD_DIR / safe_filename
        upload_file.save(local_upload_path)
        print(f"📥 已接收上传音频: {local_upload_path}")

        process_result = process_audio_file(local_upload_path, keep_debug_files=True)
        print(f"✅ 上传音频处理完成: {process_result['caseId']}")

        return jsonify({
            "success": True,
            "message": "音频上传并处理完成",
            "caseId": process_result["caseId"],
            "result": process_result["frontend_case"]
        })
    except Exception as e:
        print(f"❌ 上传音频处理失败: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/generate_summary", methods=["POST"])
def generate_summary():
    """生成智能小结"""
    try:
        data = request.json
        transcript = data.get("transcript", [])

        if not transcript:
            return jsonify({"error": "转录内容为空"}), 400

        print(f"📝 正在生成智能小结...")
        summary = build_summary(transcript)
        print(f"✅ 小结生成成功")

        return jsonify({
            "success": True,
            "summary": summary
        })

    except Exception as e:
        print(f"❌ 生成小结失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate_qc", methods=["POST"])
def generate_qc():
    """生成质检报告"""
    try:
        data = request.json
        transcript = data.get("transcript", [])

        if not transcript:
            return jsonify({"error": "转录内容为空"}), 400

        print(f"🔍 正在生成质检报告...")
        qc_report = build_qc_report(transcript)
        print(f"✅ 质检报告生成成功")

        return jsonify({
            "success": True,
            "qcReport": qc_report
        })

    except Exception as e:
        print(f"❌ 生成质检报告失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """一次性生成小结和质检报告"""
    try:
        data = request.json
        transcript = data.get("transcript", [])

        if not transcript:
            return jsonify({"error": "转录内容为空"}), 400

        print(f"🚀 开始分析通话...")
        analysis_result = analyze_transcript(transcript)
        print(f"📝 小结和质检生成完成")

        return jsonify({
            "success": True,
            "summary": analysis_result["summary"],
            "qcReport": analysis_result["qcReport"]
        })

    except Exception as e:
        print(f"❌ 分析失败: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("=" * 60)
    print("🎯 催收质检 - 智能小结 API 服务")
    print("=" * 60)
    print(f"📌 模型: {MODEL_NAME}")
    print("-" * 60)
    print("📡 API 端点:")
    print("   GET  /api/health           - 健康检查")
    print("   GET  /api/cases            - 查询案件列表")
    print("   GET  /api/cases/<case_id>  - 查询案件详情")
    print("   POST /api/upload_audio     - 上传音频并自动处理")
    print("   POST /api/generate_summary - 生成智能小结")
    print("   POST /api/generate_qc      - 生成质检报告")
    print("   POST /api/analyze          - 一次性分析")
    print("=" * 60)

    app.run(host="0.0.0.0", port=5001, debug=True)
