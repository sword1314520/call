#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频处理流水线服务

作用：
1. 把原来 process_audio.py 里的核心处理链路抽出来
2. 让“批处理脚本”和“上传接口”共用同一套逻辑
3. 保证上传 API 和离线脚本产出的结果结构一致
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict

from analysis_service import analyze_transcript
from mysql_storage import save_case_record
from oss_utils import upload_file_to_oss
from process_audio import (
    convert_m4a_to_wav,
    map_speakers_to_roles,
    parse_asr_result,
    parse_emotion_result,
    run_asr_with_speaker_diarization,
    run_emotion_recognition,
)


PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / "processed"


def build_demo_data(transcript: list, audio_info: dict, emotion_timeline: dict, summary: dict, qc_report: dict) -> dict:
    """构造前端展示用的数据对象。"""
    return {
        "caseInfo": {
            "id": f"CASE-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "customerName": "AI识别客户",
            "debtAmount": "¥--",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "agentName": "AI识别坐席",
            "duration": audio_info.get("duration", 0),
        },
        "summary": summary,
        "qcReport": qc_report,
        "emotionTimeline": emotion_timeline,
        "transcript": transcript
    }


def save_debug_outputs(base_name: str, transcript: list, final_data: dict) -> Dict:
    """
    保存本地调试文件。

    即使现在前端主要走 API，这些文件保留仍然有价值：
    1. 便于排查转录结果
    2. 便于和数据库中的结果做比对
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    js_output_path = PROJECT_ROOT / f"demo_data_{base_name}.js"
    js_content = f"const GENERATED_DATA_{base_name.upper()} = {json.dumps(final_data, ensure_ascii=False, indent=2)};"
    with open(js_output_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(js_content)

    json_output_path = OUTPUT_DIR / f"{base_name}_transcript.json"
    with open(json_output_path, "w", encoding="utf-8") as file_obj:
        json.dump(transcript, file_obj, ensure_ascii=False, indent=2)

    return {
        "js_data": str(js_output_path),
        "json_transcript": str(json_output_path)
    }


def process_audio_file(input_path: Path, keep_debug_files: bool = True) -> Dict:
    """
    处理单个音频文件并落库。

    Args:
        input_path: 上传后的本地音频路径
        keep_debug_files: 是否保留调试输出文件

    Returns:
        dict: 前端和接口都可直接使用的处理结果
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    base_name = input_path.stem
    wav_path = OUTPUT_DIR / f"{base_name}.wav"

    # 1. 音频转码
    audio, duration = convert_m4a_to_wav(input_path, wav_path)

    # 2. ASR 与说话人识别
    asr_result = run_asr_with_speaker_diarization(wav_path)
    transcript = parse_asr_result(asr_result)
    transcript = map_speakers_to_roles(transcript)

    # 3. 情感识别
    emotion_result = run_emotion_recognition(wav_path)
    emotion_timeline = parse_emotion_result(emotion_result, duration)

    # 4. 上传 OSS
    original_audio_oss = upload_file_to_oss(input_path, "original")
    wav_audio_oss = upload_file_to_oss(wav_path, "wav")

    # 5. 调用 LLM
    analysis_result = analyze_transcript(transcript)
    summary = analysis_result["summary"]
    qc_report = analysis_result["qcReport"]

    # 6. 生成统一的数据结构
    audio_info = {"duration": duration, "channels": audio.channels, "sample_rate": audio.frame_rate}
    final_data = build_demo_data(transcript, audio_info, emotion_timeline, summary, qc_report)
    case_id = final_data["caseInfo"]["id"]

    # 7. 保存数据库
    save_case_record({
        "case_id": case_id,
        "audio_file_name": input_path.name,
        "original_audio_url": original_audio_oss["signed_url"],
        "original_audio_object_key": original_audio_oss["object_key"],
        "wav_audio_url": wav_audio_oss["signed_url"],
        "wav_audio_object_key": wav_audio_oss["object_key"],
        "duration_seconds": duration,
        "transcript": transcript,
        "emotion_timeline": emotion_timeline,
        "summary": summary,
        "qc_report": qc_report
    })

    debug_outputs = {"js_data": "", "json_transcript": ""}
    if keep_debug_files:
        debug_outputs = save_debug_outputs(base_name, transcript, final_data)

    return {
        "caseId": case_id,
        "original": str(input_path),
        "wav": str(wav_path),
        "js_data": debug_outputs["js_data"],
        "json_transcript": debug_outputs["json_transcript"],
        "original_audio_url": original_audio_oss["signed_url"],
        "wav_audio_url": wav_audio_oss["signed_url"],
        "original_audio_object_key": original_audio_oss["object_key"],
        "wav_audio_object_key": wav_audio_oss["object_key"],
        "summary": summary,
        "qc_report": qc_report,
        "emotion_timeline": emotion_timeline,
        "transcript": transcript,
        "duration": duration,
        "sentence_count": len(transcript),
        "transcript_preview": transcript[:3] if transcript else [],
        "frontend_case": final_data
    }
