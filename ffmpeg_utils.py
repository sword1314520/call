#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FFmpeg 配置工具

作用：
1. 在 Windows 环境下优先使用项目目录中的 ffmpeg.exe
2. 避免 pydub 只能依赖系统 PATH，导致上传 MP3 时找不到解码程序
3. 给音频转换逻辑提供统一的本地 FFmpeg 配置入口
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).parent
LOCAL_FFMPEG_PATH = PROJECT_ROOT / "ffmpeg.exe"
LOCAL_FFPROBE_PATH = PROJECT_ROOT / "ffprobe.exe"


def configure_pydub_ffmpeg():
    """
    配置 pydub 使用本地 FFmpeg。

    说明：
    1. 如果项目目录下存在 ffmpeg.exe，则显式指定给 pydub
    2. 如果还存在 ffprobe.exe，也一并指定
    3. 如果本地文件不存在，就保持 pydub 默认行为，让它继续走系统 PATH
    """
    from pydub import AudioSegment

    if LOCAL_FFMPEG_PATH.exists():
        AudioSegment.converter = str(LOCAL_FFMPEG_PATH)
        # 某些版本的 pydub 也会读取 ffmpeg 属性，这里一起赋值更稳妥
        AudioSegment.ffmpeg = str(LOCAL_FFMPEG_PATH)

    if LOCAL_FFPROBE_PATH.exists():
        AudioSegment.ffprobe = str(LOCAL_FFPROBE_PATH)


def get_ffmpeg_status() -> dict:
    """返回本地 FFmpeg 文件检测结果，便于调试和文档说明。"""
    return {
        "project_root": str(PROJECT_ROOT),
        "ffmpeg_exists": LOCAL_FFMPEG_PATH.exists(),
        "ffmpeg_path": str(LOCAL_FFMPEG_PATH),
        "ffprobe_exists": LOCAL_FFPROBE_PATH.exists(),
        "ffprobe_path": str(LOCAL_FFPROBE_PATH),
    }
