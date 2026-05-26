#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL 存储模块

作用：
1. 保存通话分析结果
2. 自动初始化表结构
3. 把 transcript、summary、qcReport、情绪结果统一落库
"""

import datetime
import json
import os
from typing import Dict, List, Optional

import pymysql
from dotenv import load_dotenv

load_dotenv()


class MySQLConfig:
    """管理 MySQL 连接配置。"""

    HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
    PORT = int(os.getenv("MYSQL_PORT", "3306"))
    USER = os.getenv("MYSQL_USER", "root")
    PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    DATABASE = os.getenv("MYSQL_DATABASE", "debt_qc")
    CHARSET = os.getenv("MYSQL_CHARSET", "utf8mb4")
    AUTOCOMMIT = os.getenv("MYSQL_AUTOCOMMIT", "true").lower() == "true"
    CONNECT_TIMEOUT = int(os.getenv("MYSQL_CONNECT_TIMEOUT", "10"))


def get_mysql_connection():
    """创建 MySQL 连接。"""
    return pymysql.connect(
        host=MySQLConfig.HOST,
        port=MySQLConfig.PORT,
        user=MySQLConfig.USER,
        password=MySQLConfig.PASSWORD,
        database=MySQLConfig.DATABASE,
        charset=MySQLConfig.CHARSET,
        autocommit=MySQLConfig.AUTOCOMMIT,
        connect_timeout=MySQLConfig.CONNECT_TIMEOUT,
        cursorclass=pymysql.cursors.DictCursor
    )


def init_mysql_tables():
    """初始化业务表，如果表不存在则自动创建。"""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS qc_cases (
        id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
        case_id VARCHAR(64) NOT NULL COMMENT '案件编号',
        audio_file_name VARCHAR(255) NOT NULL COMMENT '原始音频文件名',
        original_audio_url TEXT COMMENT '原始音频 OSS 地址',
        original_audio_object_key VARCHAR(512) COMMENT '原始音频 OSS 对象路径',
        wav_audio_url TEXT COMMENT '转码后 WAV 音频 OSS 地址',
        wav_audio_object_key VARCHAR(512) COMMENT 'WAV 音频 OSS 对象路径',
        duration_seconds DECIMAL(10, 2) DEFAULT 0 COMMENT '音频时长',
        transcript_json LONGTEXT COMMENT 'ASR 转录结果 JSON',
        emotion_timeline_json LONGTEXT COMMENT '情绪时间轴 JSON',
        summary_json LONGTEXT COMMENT '智能小结 JSON',
        qc_report_json LONGTEXT COMMENT '质检报告 JSON',
        created_at DATETIME NOT NULL COMMENT '创建时间',
        updated_at DATETIME NOT NULL COMMENT '更新时间',
        UNIQUE KEY uk_case_id (case_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='催收质检结果表';
    """

    connection = get_mysql_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(create_table_sql)
    finally:
        connection.close()


def save_case_record(record: Dict):
    """
    保存通话分析记录到 MySQL。

    这里使用 REPLACE INTO，便于同一个 case_id 重跑时直接覆盖。
    """
    sql = """
    REPLACE INTO qc_cases (
        case_id,
        audio_file_name,
        original_audio_url,
        original_audio_object_key,
        wav_audio_url,
        wav_audio_object_key,
        duration_seconds,
        transcript_json,
        emotion_timeline_json,
        summary_json,
        qc_report_json,
        created_at,
        updated_at
    ) VALUES (
        %(case_id)s,
        %(audio_file_name)s,
        %(original_audio_url)s,
        %(original_audio_object_key)s,
        %(wav_audio_url)s,
        %(wav_audio_object_key)s,
        %(duration_seconds)s,
        %(transcript_json)s,
        %(emotion_timeline_json)s,
        %(summary_json)s,
        %(qc_report_json)s,
        NOW(),
        NOW()
    )
    """

    payload = {
        "case_id": record["case_id"],
        "audio_file_name": record["audio_file_name"],
        "original_audio_url": record["original_audio_url"],
        "original_audio_object_key": record.get("original_audio_object_key", ""),
        "wav_audio_url": record["wav_audio_url"],
        "wav_audio_object_key": record.get("wav_audio_object_key", ""),
        "duration_seconds": record["duration_seconds"],
        "transcript_json": json.dumps(record["transcript"], ensure_ascii=False),
        "emotion_timeline_json": json.dumps(record["emotion_timeline"], ensure_ascii=False),
        "summary_json": json.dumps(record["summary"], ensure_ascii=False),
        "qc_report_json": json.dumps(record["qc_report"], ensure_ascii=False),
    }

    connection = get_mysql_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, payload)
    finally:
        connection.close()


def _safe_json_loads(raw_value: Optional[str], default_value):
    """兼容数据库中为空字符串或空值的 JSON 字段。"""
    if not raw_value:
        return default_value
    try:
        return json.loads(raw_value)
    except Exception:
        return default_value


def _serialize_datetime(value):
    """把 datetime 转成前端容易处理的字符串。"""
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def get_case_record(case_id: str) -> Optional[Dict]:
    """按 case_id 查询单条案件记录。"""
    sql = """
    SELECT
        case_id,
        audio_file_name,
        original_audio_url,
        original_audio_object_key,
        wav_audio_url,
        wav_audio_object_key,
        duration_seconds,
        transcript_json,
        emotion_timeline_json,
        summary_json,
        qc_report_json,
        created_at,
        updated_at
    FROM qc_cases
    WHERE case_id = %s
    LIMIT 1
    """

    connection = get_mysql_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, (case_id,))
            return cursor.fetchone()
    finally:
        connection.close()


def list_case_records(limit: int = 100) -> List[Dict]:
    """查询案件列表，按更新时间倒序返回。"""
    sql = """
    SELECT
        case_id,
        audio_file_name,
        original_audio_url,
        original_audio_object_key,
        wav_audio_url,
        wav_audio_object_key,
        duration_seconds,
        transcript_json,
        emotion_timeline_json,
        summary_json,
        qc_report_json,
        created_at,
        updated_at
    FROM qc_cases
    ORDER BY updated_at DESC
    LIMIT %s
    """

    connection = get_mysql_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, (limit,))
            return cursor.fetchall()
    finally:
        connection.close()


def format_case_record(row: Dict) -> Dict:
    """把数据库记录整理成前端接口直接可用的结构。"""
    return {
        "caseInfo": {
            "id": row["case_id"],
            "customerName": "AI识别客户",
            "debtAmount": "¥--",
            "date": _serialize_datetime(row.get("created_at")),
            "agentName": "AI识别坐席",
            "duration": float(row.get("duration_seconds") or 0),
            "audioFileName": row.get("audio_file_name", "")
        },
        "storage": {
            "originalAudioUrl": row.get("original_audio_url", ""),
            "originalAudioObjectKey": row.get("original_audio_object_key", ""),
            "wavAudioUrl": row.get("wav_audio_url", ""),
            "wavAudioObjectKey": row.get("wav_audio_object_key", "")
        },
        "summary": _safe_json_loads(row.get("summary_json"), {}),
        "qcReport": _safe_json_loads(row.get("qc_report_json"), {"score": 0, "violations": []}),
        "emotionTimeline": _safe_json_loads(
            row.get("emotion_timeline_json"),
            {"agent": [{"emotion": "neutral", "duration": 1}], "customer": [{"emotion": "neutral", "duration": 1}]}
        ),
        "transcript": _safe_json_loads(row.get("transcript_json"), []),
        "createdAt": _serialize_datetime(row.get("created_at")),
        "updatedAt": _serialize_datetime(row.get("updated_at"))
    }
