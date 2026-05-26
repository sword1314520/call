#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
催收质检音频处理脚本

功能:
1. 将 m4a 音频转换为 wav 格式
2. 使用 FunASR 进行语音识别 + 说话人分离
3. 使用 emotion2vec 进行语音情感识别
4. 生成前端可读取的结构化数据

使用方法:
    python process_audio.py

依赖:
    pip install pydub funasr torch torchaudio modelscope
    brew install ffmpeg  # macOS
"""

import os
import json
import subprocess
import wave
from pathlib import Path
from datetime import datetime
from analysis_service import analyze_transcript
from ffmpeg_utils import get_local_ffmpeg_path
from mysql_storage import init_mysql_tables, save_case_record
from oss_utils import upload_file_to_oss

# ================= 配置区域 =================
AUDIO_DIR = Path(__file__).parent / "audio"  # 原始音频目录
OUTPUT_DIR = Path(__file__).parent / "processed"  # 输出目录
PROJECT_ROOT = Path(__file__).parent


# ===========================================


def convert_m4a_to_wav(input_path: Path, output_path: Path):
    """
    将 m4a 文件转换为 wav 格式

    Args:
        input_path: 输入的 m4a 文件路径
        output_path: 输出的 wav 文件路径

    Returns:
        tuple: (音频对象, 时长秒数)
    """
    print(f"📂 [加载] 读取音频文件: {input_path.name}")
    ffmpeg_path = get_local_ffmpeg_path()

    # 这里直接调用本地 ffmpeg.exe 转码，避免 pydub 额外依赖 ffprobe 导致 WinError 2
    command = [
        ffmpeg_path,
        "-y",
        "-i", str(input_path),
        "-ar", "16000",
        "-ac", "1",
        str(output_path)
    ]

    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print("❌ 错误: ffmpeg 转码失败")
        print(f"   ffmpeg 路径: {ffmpeg_path}")
        print(f"   错误详情: {e.stderr}")
        raise RuntimeError(f"ffmpeg 转码失败: {e.stderr}") from e

    if not output_path.exists():
        raise FileNotFoundError(f"转码后的 WAV 文件不存在: {output_path}")

    # 通过标准库读取 WAV 信息，不再依赖 pydub
    with wave.open(str(output_path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        duration_sec = frame_count / float(sample_rate) if sample_rate else 0

    print(f"   ├─ 时长: {duration_sec:.2f} 秒")
    print(f"   ├─ 声道数: {channels} ({'立体声' if channels == 2 else '单声道'})")
    print(f"   └─ 采样率: {sample_rate} Hz")
    print(f"🔄 [转码] 导出 WAV 文件: {output_path.name}")
    print(f"   └─ 大小: {output_path.stat().st_size / 1024 / 1024:.2f} MB (16kHz 单声道)")

    audio_info = {
        "channels": channels,
        "sample_rate": sample_rate
    }
    return audio_info, duration_sec


def run_asr_with_speaker_diarization(wav_path: Path):
    """
    使用 FunASR Paraformer + CAM++ 进行语音识别和说话人分离

    Args:
        wav_path: WAV 音频文件路径

    Returns:
        list: 带时间戳和说话人标签的转录结果
    """
    import torch
    from funasr import AutoModel

    print(f"🎤 [ASR] 正在加载 FunASR 模型...")

    # 检测设备
    if torch.cuda.is_available():
        device = "cuda:0"
        print(f"   └─ 使用 GPU: CUDA")
    elif torch.backends.mps.is_available():
        device = "mps"
        print(f"   └─ 使用 GPU: Apple MPS")
    else:
        device = "cpu"
        print(f"   └─ 使用 CPU")

    # 加载模型: paraformer-zh + VAD + 标点 + 说话人分离
    # 注意: spk_model="cam++" 启用说话人分离功能
    print(f"⏳ [加载] 初始化模型（首次运行需下载，约 1GB）...")

    model = AutoModel(
        model="paraformer-zh",  # 中文语音识别模型
        vad_model="fsmn-vad",  # 语音活动检测
        punc_model="ct-punc",  # 标点恢复
        spk_model="cam++",  # 说话人分离 (CAM++)
        device=device,
    )

    print(f"✅ [加载] 模型加载完成")
    print(f"🔊 [识别] 正在进行语音识别 + 说话人分离...")

    # 执行识别
    res = model.generate(
        input=str(wav_path),
        batch_size_s=300,  # 动态批处理，单位秒
    )

    print(f"✅ [识别] 识别完成")

    return res


def run_emotion_recognition(wav_path: Path):
    """
    使用 emotion2vec 进行语音情感识别

    Args:
        wav_path: WAV 音频文件路径

    Returns:
        list: 情感识别结果
    """
    import torch
    from funasr import AutoModel

    print(f"😊 [情感] 正在加载 emotion2vec 模型...")

    # 检测设备
    if torch.cuda.is_available():
        device = "cuda:0"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"

    try:
        # 加载情感识别模型
        emotion_model = AutoModel(
            model="iic/emotion2vec_plus_large",
            device=device,
        )

        print(f"✅ [情感] 模型加载完成")
        print(f"🔍 [情感] 正在分析语音情绪...")

        # 执行情感识别
        res = emotion_model.generate(
            input=str(wav_path),
            granularity="utterance",  # 句子级别
            extract_embedding=False,
        )

        print(f"✅ [情感] 情感分析完成")

        return res
    except Exception as e:
        print(f"⚠️  情感识别失败 (但不影响主流程): {e}")
        return None


def parse_emotion_result(emotion_result, duration: float) -> dict:
    """
    解析情感识别结果，生成情绪时间轴数据

    emotion2vec 输出的情绪类别:
    - angry: 愤怒
    - disgusted: 厌恶
    - fearful: 恐惧
    - happy: 快乐
    - neutral: 中性
    - other: 其他
    - sad: 悲伤
    - surprised: 惊讶
    - unknown: 未知

    Args:
        emotion_result: emotion2vec 返回的结果
        duration: 音频时长（秒）

    Returns:
        dict: 情绪时间轴数据
    """
    print(f"🎨 [解析] 正在解析情绪数据...")

    # 默认情绪时间轴
    default_timeline = {
        "agent": [{"emotion": "neutral", "duration": 1}],
        "customer": [{"emotion": "neutral", "duration": 1}]
    }

    if not emotion_result or len(emotion_result) == 0:
        print(f"   └─ 使用默认情绪数据")
        return default_timeline

    try:
        result = emotion_result[0]

        # 获取情绪标签和分数
        labels = result.get("labels", [])
        scores = result.get("scores", [])

        if labels and scores:
            # 找到主要情绪
            main_emotion_idx = scores.index(max(scores))
            main_emotion = labels[main_emotion_idx]

            print(f"   └─ 主要情绪: {main_emotion} (置信度: {max(scores):.2f})")

            # 映射到前端支持的情绪类型（同时支持中英文标签）
            emotion_map = {
                # 英文标签
                "angry": "angry",
                "disgusted": "negative",
                "fearful": "negative",
                "happy": "positive",
                "neutral": "neutral",
                "other": "neutral",
                "sad": "negative",
                "surprised": "neutral",
                "unknown": "neutral",
                # 中文标签
                "愤怒": "angry",
                "厌恶": "negative",
                "恐惧": "negative",
                "开心": "positive",
                "高兴": "positive",
                "中性": "neutral",
                "其他": "neutral",
                "难过": "negative",
                "悲伤": "negative",
                "惊讶": "neutral",
                "生气": "angry",
                # 常见变体
                "难过/sad": "negative",
                "生气/angry": "angry",
                "开心/happy": "positive",
            }

            mapped_emotion = emotion_map.get(main_emotion, "neutral")

            # 如果没找到匹配，检查是否包含关键词
            if mapped_emotion == "neutral" and main_emotion not in ["neutral", "中性", "other", "其他"]:
                main_lower = main_emotion.lower()
                if "sad" in main_lower or "难过" in main_emotion or "悲" in main_emotion:
                    mapped_emotion = "negative"
                elif "angry" in main_lower or "愤怒" in main_emotion or "生气" in main_emotion:
                    mapped_emotion = "angry"
                elif "happy" in main_lower or "开心" in main_emotion or "高兴" in main_emotion:
                    mapped_emotion = "positive"

            print(f"   └─ 映射后情绪: {mapped_emotion}")

            # 坐席更中性，客户情绪更明显
            return {
                "agent": [{"emotion": "neutral", "duration": 0.7}, {"emotion": mapped_emotion, "duration": 0.3}],
                "customer": [{"emotion": "neutral", "duration": 0.3}, {"emotion": mapped_emotion, "duration": 0.7}]
            }
        else:
            print(f"   └─ 未获取到情绪标签，使用默认值")
            return default_timeline

    except Exception as e:
        print(f"   └─ 解析失败: {e}，使用默认值")
        return default_timeline


def parse_asr_result(asr_result) -> list:
    """
    解析 FunASR 的识别结果，提取带时间戳和说话人的文本

    Args:
        asr_result: FunASR 返回的原始结果

    Returns:
        list: 格式化的转录列表
    """
    print(f"📝 [解析] 正在解析识别结果...")

    if not asr_result or len(asr_result) == 0:
        print("⚠️  警告: ASR 结果为空")
        return []

    result = asr_result[0]

    # 打印原始结果用于调试
    print(f"   └─ 原始结果键: {result.keys() if isinstance(result, dict) else type(result)}")

    transcript = []

    # FunASR 的结果格式可能包含:
    # - text: 完整文本
    # - sentence_info: 句子级别的信息（包含时间戳和说话人）
    # - spk_embedding: 说话人嵌入向量

    if isinstance(result, dict):
        # 检查是否有句子级别的信息
        if "sentence_info" in result:
            sentences = result["sentence_info"]
            for sent in sentences:
                item = {
                    "text": sent.get("text", ""),
                    "start": sent.get("start", 0) / 1000,  # 转换为秒
                    "end": sent.get("end", 0) / 1000,
                    "speaker": f"说话人{sent.get('spk', 0) + 1}" if "spk" in sent else "未知"
                }
                transcript.append(item)
                print(f"   ├─ [{item['start']:.1f}s-{item['end']:.1f}s] {item['speaker']}: {item['text'][:30]}...")

        # 如果没有 sentence_info，尝试使用 timestamp 信息
        elif "timestamp" in result:
            text = result.get("text", "")
            timestamps = result.get("timestamp", [])
            spk_info = result.get("spk", [])

            # 按句子分割处理
            # 这里需要根据实际返回格式调整
            item = {
                "text": text,
                "start": 0,
                "end": 0,
                "speaker": "未知"
            }

            if timestamps and len(timestamps) > 0:
                if isinstance(timestamps[0], list) and len(timestamps[0]) == 2:
                    item["start"] = timestamps[0][0] / 1000
                    item["end"] = timestamps[-1][1] / 1000

            transcript.append(item)
            print(f"   └─ 整段文本: {text[:50]}...")

        else:
            # 最简单的情况：只有 text
            text = result.get("text", str(result))
            transcript.append({
                "text": text,
                "start": 0,
                "end": 0,
                "speaker": "未知"
            })
            print(f"   └─ 纯文本: {text[:50]}...")

    print(f"✅ [解析] 共解析 {len(transcript)} 条记录")

    return transcript


def map_speakers_to_roles(transcript: list) -> list:
    """
    将说话人标签映射为角色（坐席/客户）

    基于启发式规则：
    - 通常坐席先说话（开场白）
    - 或者根据说话频率判断

    Args:
        transcript: 转录列表

    Returns:
        list: 带角色标签的转录列表
    """
    print(f"🏷️  [映射] 正在将说话人映射为角色...")

    if not transcript:
        return transcript

    # 统计每个说话人的出现次数和首次出现位置
    speaker_stats = {}
    for i, item in enumerate(transcript):
        spk = item.get("speaker", "未知")
        if spk not in speaker_stats:
            speaker_stats[spk] = {"count": 0, "first_index": i}
        speaker_stats[spk]["count"] += 1

    print(f"   └─ 检测到说话人: {list(speaker_stats.keys())}")

    # 简单规则: 第一个说话的人是坐席
    speakers = sorted(speaker_stats.keys(), key=lambda x: speaker_stats[x]["first_index"])

    role_mapping = {}
    if len(speakers) >= 2:
        role_mapping[speakers[0]] = "坐席"
        role_mapping[speakers[1]] = "客户"
        for spk in speakers[2:]:
            role_mapping[spk] = f"其他({spk})"
    elif len(speakers) == 1:
        # 只有一个说话人，默认为坐席
        role_mapping[speakers[0]] = "坐席"

    print(f"   └─ 角色映射: {role_mapping}")

    # 应用映射
    for item in transcript:
        spk = item.get("speaker", "未知")
        item["speaker"] = role_mapping.get(spk, spk)

    return transcript


def generate_demo_data_js(transcript: list, audio_info: dict, emotion_timeline: dict, output_path: Path,
                          base_name: str, summary: dict = None, qc_report: dict = None):
    """
    生成前端可读取的 demo_data.js 文件

    Args:
        transcript: 转录列表
        audio_info: 音频信息
        emotion_timeline: 情绪时间轴数据
        output_path: 输出文件路径
        base_name: 音频文件基础名（用于生成唯一变量名）
    """
    print(f"📄 [生成] 正在生成前端数据文件...")

    # 构造完整的数据对象 (匹配前端 MOCK_DATA 结构)
    final_data = {
        "caseInfo": {
            "id": f"CASE-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "customerName": "AI识别客户",
            "debtAmount": "¥--",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "agentName": "AI识别坐席",
            "duration": audio_info.get("duration", 0),
        },
        "summary": {
            "联系结果类标签": {"通话状态": "可联", "承诺还款": "待确认"},
            "客户画像类标签": {"还款意愿": "待分析", "经济状况": "待分析"},
            "行动项标签": {"下次联系时间": "待定", "风险等级": "待评估"}
        } if summary is None else summary,
        "qcReport": {
            "score": 0,  # 质检评分待实现
            "violations": []
        } if qc_report is None else qc_report,
        "emotionTimeline": emotion_timeline,
        "transcript": transcript
    }

    # 生成唯一的变量名（如 GENERATED_DATA_AUDIO1）
    var_name = f"GENERATED_DATA_{base_name.upper()}"
    js_content = f"const {var_name} = {json.dumps(final_data, ensure_ascii=False, indent=2)};"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(js_content)

    print(f"✅ [生成] 数据已保存至: {output_path.name} (变量名: {var_name})")

    return final_data


def process_single_audio(input_path: Path, output_dir: Path) -> dict:
    """
    处理单个音频文件：转换 + ASR + 说话人分离

    Args:
        input_path: 输入音频路径
        output_dir: 输出目录

    Returns:
        dict: 处理结果信息
    """
    base_name = input_path.stem  # 获取不带扩展名的文件名

    # 1. 转换格式
    wav_path = output_dir / f"{base_name}.wav"
    audio_info, duration = convert_m4a_to_wav(input_path, wav_path)

    # 2. ASR + 说话人分离
    asr_result = run_asr_with_speaker_diarization(wav_path)

    # 3. 解析结果
    transcript = parse_asr_result(asr_result)

    # 4. 说话人角色映射
    transcript = map_speakers_to_roles(transcript)

    # 5. 情感识别
    emotion_result = run_emotion_recognition(wav_path)
    emotion_timeline = parse_emotion_result(emotion_result, duration)

    # 6. 上传音频到阿里云 OSS
    print("☁️  [OSS] 正在上传原始音频到阿里云 OSS...")
    original_audio_oss = upload_file_to_oss(input_path, "original")
    print(f"   └─ 原始音频已上传: {original_audio_oss['object_key']}")

    print("☁️  [OSS] 正在上传 WAV 音频到阿里云 OSS...")
    wav_audio_oss = upload_file_to_oss(wav_path, "wav")
    print(f"   └─ WAV 音频已上传: {wav_audio_oss['object_key']}")

    # 7. 调用 LLM 生成智能小结和质检报告
    print("🤖 [LLM] 正在生成智能小结和质检报告...")
    analysis_result = analyze_transcript(transcript)
    summary = analysis_result["summary"]
    qc_report = analysis_result["qcReport"]
    print("✅ [LLM] 智能分析完成")

    # 8. 生成前端数据文件
    js_output_path = PROJECT_ROOT / f"demo_data_{base_name}.js"
    audio_info = {"duration": duration, "channels": audio_info["channels"], "sample_rate": audio_info["sample_rate"]}
    final_data = generate_demo_data_js(
        transcript,
        audio_info,
        emotion_timeline,
        js_output_path,
        base_name,
        summary=summary,
        qc_report=qc_report
    )

    # 9. 同时保存 JSON 格式（便于调试）
    json_output_path = output_dir / f"{base_name}_transcript.json"
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)

    # 10. 保存分析结果到 MySQL
    case_id = final_data["caseInfo"]["id"]
    print("🗄️  [MySQL] 正在保存分析结果到数据库...")
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
    print(f"✅ [MySQL] 案件 {case_id} 已保存")

    return {
        "original": str(input_path),
        "wav": str(wav_path),
        "js_data": str(js_output_path),
        "json_transcript": str(json_output_path),
        "original_audio_url": original_audio_oss["signed_url"],
        "wav_audio_url": wav_audio_oss["signed_url"],
        "summary": summary,
        "qc_report": qc_report,
        "duration": duration,
        "sentence_count": len(transcript),
        "transcript_preview": transcript[:3] if transcript else []
    }


def main():
    """主函数：处理 audio 目录下的所有 m4a 文件"""
    print("=" * 60)
    print("🎯 催收质检音频处理脚本")
    print("   FunASR + CAM++ 说话人分离 + emotion2vec 情感识别")
    print("=" * 60)

    # 检查音频目录
    if not AUDIO_DIR.exists():
        print(f"❌ 错误: 音频目录不存在: {AUDIO_DIR}")
        return

    # 创建输出目录
    OUTPUT_DIR.mkdir(exist_ok=True)
    init_mysql_tables()
    print(f"📁 输入目录: {AUDIO_DIR}")
    print(f"📁 输出目录: {OUTPUT_DIR}")
    print("-" * 60)

    # 查找所有 m4a 文件
    m4a_files = list(AUDIO_DIR.glob("*.m4a"))

    # 也支持 wav 文件
    wav_files = list(AUDIO_DIR.glob("*.wav"))
    all_files = m4a_files + wav_files

    if not all_files:
        print(f"⚠️  警告: 在 {AUDIO_DIR} 中未找到音频文件")
        return

    print(f"📋 找到 {len(all_files)} 个音频文件待处理")
    print("-" * 60)

    results = []

    for i, audio_path in enumerate(all_files, 1):
        print(f"\n{'=' * 60}")
        print(f"[{i}/{len(all_files)}] 处理: {audio_path.name}")
        print("=" * 60)

        try:
            result = process_single_audio(audio_path, OUTPUT_DIR)
            results.append(result)
        except Exception as e:
            print(f"❌ 处理失败: {e}")
            import traceback
            traceback.print_exc()
            continue

    # 输出汇总
    print("\n" + "=" * 60)
    print("📊 处理汇总")
    print("=" * 60)

    for result in results:
        print(f"\n📄 {Path(result['original']).name}")
        print(f"   ├─ WAV 文件: {Path(result['wav']).name}")
        print(f"   ├─ JS 数据: {Path(result['js_data']).name}")
        print(f"   ├─ 时长: {result['duration']:.2f} 秒")
        print(f"   ├─ 识别句子数: {result['sentence_count']}")
        if result['transcript_preview']:
            print(f"   └─ 预览:")
            for item in result['transcript_preview']:
                print(f"      - [{item.get('speaker', '?')}] {item.get('text', '')[:40]}...")

    print("\n" + "=" * 60)
    print("✅ 音频处理完成！")
    print("=" * 60)

    # 保存处理结果为 JSON
    result_json = OUTPUT_DIR / "process_result.json"
    with open(result_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n📝 处理结果已保存至: {result_json}")

    # 提示下一步
    print("\n💡 下一步操作:")
    print("   1. 在 催收质检.html 中引入生成的 demo_data_xxx.js")
    print("   2. 使用 Live Server 打开 HTML 查看效果")


if __name__ == "__main__":
    main()
