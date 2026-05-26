#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 分析公共服务

作用：
1. 统一封装智能小结和质检报告的生成逻辑
2. 让 api_server.py 和 process_audio.py 复用同一套分析代码
3. 避免相同的 Prompt 和 JSON 解析逻辑重复维护
"""

import json
import os
import re
from typing import Dict, List

import requests
from dotenv import load_dotenv

# 加载环境变量，便于读取模型和 API Key 配置
load_dotenv()

OPENROUTER_API_KEY = os.getenv("openrouter_api_key")
MODEL_NAME = os.getenv("model_name", "deepseek/deepseek-v3.2")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
#地址和钥匙和模型
#transcript占位符，把实际内容传过来
# 智能小结 Prompt
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

# 质检 Prompt
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
    """调用 OpenRouter 接口，返回模型输出文本。"""
    """输入：prompt（你给 AI 的问题 / 指令） 输出：字符串（AI 给你的回答）"""
    if not OPENROUTER_API_KEY:
        raise ValueError("未配置 openrouter_api_key，请先检查 .env 文件")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json; charset=utf-8",
        "HTTP-Referer": "http://localhost:8080",
        "X-Title": "DebtCollectionQC"
    }

    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2000
    }

    response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    result = response.json()
    """网络传过来的 JSON是一串【文字字符串】 Python 不能直接用,用.json () 把它 → 变成【字典 / 对象】，才能读取"""
    return result["choices"][0]["message"]["content"]


def extract_json_from_response(response: str) -> Dict:
    """从模型响应中提取 JSON，兼容纯 JSON 和 markdown 代码块格式。"""
    try:
        return json.loads(response)
    except Exception:
        pass

    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except Exception:
            pass

    start = response.find("{")
    end = response.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(response[start:end + 1])
        except Exception:
            pass

    raise ValueError("无法从响应中提取 JSON")


def format_transcript(transcript: List[Dict]) -> str:
    """将转录数组拼成便于 LLM 理解的文本格式。"""
    lines = []
    for item in transcript:
        speaker = item.get("speaker", "未知")
        text = item.get("text", "")
        lines.append(f"[{speaker}]: {text}")
    return "\n".join(lines)


def generate_summary(transcript: List[Dict]) -> Dict:
    """根据转录内容生成智能小结。"""
    transcript_text = format_transcript(transcript)
    prompt = SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript_text)
    response = call_llm(prompt)
    return extract_json_from_response(response)


def generate_qc_report(transcript: List[Dict]) -> Dict:
    """根据转录内容生成质检报告。"""
    transcript_text = format_transcript(transcript)
    prompt = QC_PROMPT_TEMPLATE.format(transcript=transcript_text)
    response = call_llm(prompt)
    return extract_json_from_response(response)


def analyze_transcript(transcript: List[Dict]) -> Dict:
    """一次性生成小结和质检结果，供批处理脚本和接口复用。"""
    summary = generate_summary(transcript)
    qc_report = generate_qc_report(transcript)
    return {
        "summary": summary,
        "qcReport": qc_report
    }
