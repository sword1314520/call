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

import sys
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from analysis_service import (
    MODEL_NAME,
    analyze_transcript,
    generate_qc_report as build_qc_report,
    generate_summary as build_summary,
)

# 加载环境变量
load_dotenv()
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # ✅ 中文 JSON 不转义
CORS(app)  # 允许跨域请求


@app.route("/api/health", methods=["GET"])
def health_check():
    """健康检查"""
    return jsonify({"status": "ok", "model": MODEL_NAME})


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
    print("   POST /api/generate_summary - 生成智能小结")
    print("   POST /api/generate_qc      - 生成质检报告")
    print("   POST /api/analyze          - 一次性分析")
    print("=" * 60)

    app.run(host="0.0.0.0", port=5001, debug=True)
