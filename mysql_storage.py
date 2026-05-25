#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL 存储模块

作用：
1. 保存通话分析结果
2. 自动初始化表结构
3. 把 transcript、summary、qcReport、情绪结果统一落库
"""

import json
import os
from typing import Dict

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
        wav_audio_url TEXT COMMENT '转码后 WAV 音频 OSS 地址',
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
        wav_audio_url,
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
        %(wav_audio_url)s,
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
        "wav_audio_url": record["wav_audio_url"],
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
