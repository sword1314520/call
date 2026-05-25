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
import json
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import requests

# 加载环境变量
load_dotenv()
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # ✅ 中文 JSON 不转义
CORS(app)  # 允许跨域请求

# 配置
OPENROUTER_API_KEY = os.getenv("openrouter_api_key")
MODEL_NAME = os.getenv("model_name", "deepseek/deepseek-v3.2")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# 智能小结的 Prompt 模板
SUMMARY_PROMPT_TEMPLATE = """你是一个专业的催收通话质检分析师。请根据以下通话转录内容，提取关键信息并生成结构化的小结标签。

## 通话转录内容：
{transcript}

## 请严格按照以下 JSON 格式输出标签，不要输出任何其他内容：

```json
{{
  "联系结果类标签": {{
    "通话状态": "可联/无人接听/拒接/空号/停机",
    "承诺还款": "是/否/是 (模糊)",
    "还款金额": "具体金额或'未提及'",
    "还款日期": "具体日期或'未提及'"
  }},
  "客户画像类标签": {{
    "还款意愿": "高/中/低/未知",
    "经济状况": "正常/紧张/困难/未知",
    "协商态度": "合作/犹豫/对抗/拒绝沟通",
    "投诉倾向": "无/低/中/高"
  }},
  "行动项标签": {{
    "下次联系时间": "具体日期或'待定'",
    "待办事项": "简短描述需要跟进的事项",
    "风险等级": "低/中/高/极高"
  }}
}}
```

请仔细分析对话内容，准确提取信息。如果某项信息在对话中未明确提及，请标注为"未提及"或"待定"。
"""

# 质检评分的 Prompt 模板
QC_PROMPT_TEMPLATE = """你是一个专业的催收通话质检专家。请根据以下通话转录内容，检测是否存在违规行为。

## 通话转录内容：
{transcript}

## 质检规则：
1. R001 - 身份确认（扣10分）：通话开始时必须确认客户身份，如"请问是XX先生/女士吗？"
2. R002 - 禁止威胁恐吓（扣30分）：严禁使用威胁、恐吓性语言，如"坐牢"、"黑名单"、"法院抓人"等
3. R003 - 录音告知（扣10分）：通话开始时应告知客户本次通话将被录音
4. R004 - 礼貌用语（扣5分）：使用礼貌用语，如"您好"、"请"、"谢谢"等
5. R005 - 情绪控制（扣10分）：坐席应保持情绪稳定，不得与客户发生争吵

## 请严格按照以下 JSON 格式输出质检结果，不要输出任何其他内容：

```json
{{
  "score": 100,
  "violations": [
    {{
      "ruleId": "规则ID如R001",
      "ruleName": "规则名称",
      "penalty": 扣分数值,
      "evidence": "违规的具体对话内容",
      "suggestion": "改进建议"
    }}
  ]
}}
```

注意：
- 初始分数为100分
- 每发现一项违规，从总分中扣除对应分数
- violations 数组中列出所有发现的违规项
- 如果没有违规，violations 为空数组 []
"""


def call_llm(prompt: str) -> str:
    """调用 OpenRouter LLM API"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json; charset=utf-8",
        "HTTP-Referer": "http://localhost:8080",
        "X-Title": "DebtCollectionQC"  # 改用 ASCII 字符，避免编码问题
    }

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,  # 降低随机性，保证输出稳定
        "max_tokens": 2000
    }

    try:
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"LLM API 调用失败: {e}")
        raise


def extract_json_from_response(response: str) -> dict:
    """从 LLM 响应中提取 JSON"""
    # 尝试直接解析
    try:
        return json.loads(response)
    except:
        pass

    # 尝试从 markdown 代码块中提取
    import re
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except:
            pass

    # 尝试找到第一个 { 和最后一个 }
    start = response.find('{')
    end = response.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(response[start:end + 1])
        except:
            pass

    raise ValueError("无法从响应中提取 JSON")


def format_transcript(transcript: list) -> str:
    """将转录列表格式化为文本"""
    lines = []
    for item in transcript:
        speaker = item.get("speaker", "未知")
        text = item.get("text", "")
        lines.append(f"[{speaker}]: {text}")
    return "\n".join(lines)


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

        # 格式化转录内容
        transcript_text = format_transcript(transcript)

        # 构建 prompt
        prompt = SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript_text)

        # 调用 LLM
        print(f"📝 正在生成智能小结...")
        response = call_llm(prompt)
        print(f"✅ LLM 响应成功")

        # 提取 JSON
        summary = extract_json_from_response(response)

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

        # 格式化转录内容
        transcript_text = format_transcript(transcript)

        # 构建 prompt
        prompt = QC_PROMPT_TEMPLATE.format(transcript=transcript_text)

        # 调用 LLM
        print(f"🔍 正在生成质检报告...")
        response = call_llm(prompt)
        print(f"✅ LLM 响应成功")

        # 提取 JSON
        qc_report = extract_json_from_response(response)

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

        transcript_text = format_transcript(transcript)

        # 并行生成（这里简化为顺序调用）
        print(f"🚀 开始分析通话...")

        # 生成小结
        summary_prompt = SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript_text)
        summary_response = call_llm(summary_prompt)
        summary = extract_json_from_response(summary_response)
        print(f"📝 小结生成完成")

        # 生成质检
        qc_prompt = QC_PROMPT_TEMPLATE.format(transcript=transcript_text)
        qc_response = call_llm(qc_prompt)
        qc_report = extract_json_from_response(qc_response)
        print(f"🔍 质检完成")

        return jsonify({
            "success": True,
            "summary": summary,
            "qcReport": qc_report
        })

    except Exception as e:
        print(f"❌ 分析失败: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("=" * 60)
    print("🎯 催收质检 - 智能小结 API 服务")
    print("=" * 60)
    print(f"📌 模型: {MODEL_NAME}")
    print(f"📌 API Key: {OPENROUTER_API_KEY[:20]}...")
    print("-" * 60)
    print("📡 API 端点:")
    print("   GET  /api/health           - 健康检查")
    print("   POST /api/generate_summary - 生成智能小结")
    print("   POST /api/generate_qc      - 生成质检报告")
    print("   POST /api/analyze          - 一次性分析")
    print("=" * 60)

    app.run(host="0.0.0.0", port=5001, debug=True)
