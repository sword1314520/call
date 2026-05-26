#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阿里云 OSS 工具模块

作用：
1. 统一管理 OSS 配置
2. 负责把音频文件上传到阿里云 OSS
3. 返回可用于数据库落库的对象路径和访问地址
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Dict

import oss2
from dotenv import load_dotenv

load_dotenv()


class OSSConfig:
    """集中管理阿里云 OSS 配置。"""

    ENDPOINT = os.getenv("OSS_ENDPOINT", "")
    BUCKET_NAME = os.getenv("OSS_BUCKET_NAME", "")
    ACCESS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID", "")
    ACCESS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET", "")
    URL_EXPIRE_SECONDS = int(os.getenv("OSS_URL_EXPIRE_SECONDS", "3600"))
    AUDIO_PREFIX = os.getenv("OSS_AUDIO_PREFIX", "debt-qc/audio")


def _validate_oss_config():
    """上传前检查 OSS 配置是否完整。"""
    required_values = {
        "OSS_ENDPOINT": OSSConfig.ENDPOINT,
        "OSS_BUCKET_NAME": OSSConfig.BUCKET_NAME,
        "OSS_ACCESS_KEY_ID": OSSConfig.ACCESS_KEY_ID,
        "OSS_ACCESS_KEY_SECRET": OSSConfig.ACCESS_KEY_SECRET,
    }
    missing_keys = [key for key, value in required_values.items() if not value]
    if missing_keys:
        raise ValueError(f"OSS 配置不完整，缺少: {', '.join(missing_keys)}")


def get_bucket():
    """创建 OSS Bucket 对象。"""
    _validate_oss_config()
    auth = oss2.Auth(OSSConfig.ACCESS_KEY_ID, OSSConfig.ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, OSSConfig.ENDPOINT, OSSConfig.BUCKET_NAME)


def build_object_key(file_path: Path, category: str) -> str:
    """按照日期和分类生成 OSS 对象名，便于后续检索。"""
    date_path = datetime.now().strftime("%Y/%m/%d")
    return f"{OSSConfig.AUDIO_PREFIX}/{category}/{date_path}/{file_path.name}"


def upload_file_to_oss(file_path: Path, category: str) -> Dict:
    """
    上传单个文件到 OSS。

    Args:
        file_path: 本地文件路径
        category: 文件分类，例如 original 或 wav

    Returns:
        dict: 上传结果，包含对象 key 和访问 URL
    """
    if not file_path.exists():
        raise FileNotFoundError(f"待上传文件不存在: {file_path}")

    bucket = get_bucket()
    object_key = build_object_key(file_path, category)

    # put_object_from_file 会把本地文件直接上传到 OSS
    bucket.put_object_from_file(object_key, str(file_path))

    # 这里生成一个临时签名 URL，便于开发阶段直接访问验证
    signed_url = bucket.sign_url("GET", object_key, OSSConfig.URL_EXPIRE_SECONDS)

    return {
        "bucket_name": OSSConfig.BUCKET_NAME,
        "endpoint": OSSConfig.ENDPOINT,
        "object_key": object_key,
        "signed_url": signed_url,
    }


def sign_existing_object_url(object_key: str) -> str:
    """
    为已经存在于 OSS 中的对象重新生成签名 URL。

    这样数据库里只要保存 object_key，前端查询时就能拿到最新的临时访问地址。
    """
    if not object_key:
        return ""

    bucket = get_bucket()
    return bucket.sign_url("GET", object_key, OSSConfig.URL_EXPIRE_SECONDS)
