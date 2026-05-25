#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL 配置示例文件

这个文件的目标不是直接接入你当前业务，而是帮助你理解：
1. Python 项目里 MySQL 一般怎么配置
2. 常见配置项分别是什么意思
3. 代码里通常怎么读取配置并建立连接

依赖安装：
    pip install pymysql python-dotenv
"""

import os
from dotenv import load_dotenv
import pymysql

# 读取 .env 文件中的配置
load_dotenv()


class MySQLConfig:
    """集中管理 MySQL 配置，实际项目里通常会这样封装。"""

    # 数据库主机地址
    HOST = os.getenv("MYSQL_HOST", "127.0.0.1")

    # 数据库端口，MySQL 默认端口一般是 3306
    PORT = int(os.getenv("MYSQL_PORT", "3306"))

    # 登录数据库的用户名
    USER = os.getenv("MYSQL_USER", "root")

    # 登录数据库的密码
    PASSWORD = os.getenv("MYSQL_PASSWORD", "123456")

    # 要连接的数据库名称
    DATABASE = os.getenv("MYSQL_DATABASE", "test_db")

    # 字符集建议用 utf8mb4，兼容中文和 emoji
    CHARSET = os.getenv("MYSQL_CHARSET", "utf8mb4")

    # 自动提交事务，简单项目常设为 True
    AUTOCOMMIT = os.getenv("MYSQL_AUTOCOMMIT", "true").lower() == "true"

    # 连接超时时间，单位秒
    CONNECT_TIMEOUT = int(os.getenv("MYSQL_CONNECT_TIMEOUT", "10"))


def get_mysql_connection():
    """
    创建并返回一个 MySQL 连接。

    这就是项目里最常见的“数据库连接配置代码”。
    """
    connection = pymysql.connect(
        host=MySQLConfig.HOST,
        port=MySQLConfig.PORT,
        user=MySQLConfig.USER,
        password=MySQLConfig.PASSWORD,
        database=MySQLConfig.DATABASE,
        charset=MySQLConfig.CHARSET,
        autocommit=MySQLConfig.AUTOCOMMIT,
        connect_timeout=MySQLConfig.CONNECT_TIMEOUT,

        # 返回结果用字典格式，更容易看字段名
        cursorclass=pymysql.cursors.DictCursor
    )
    return connection


def test_mysql_connection():
    """测试数据库是否连通，并执行一条最简单的 SQL。"""
    connection = None
    try:
        connection = get_mysql_connection()
        print("MySQL 连接成功")

        with connection.cursor() as cursor:
            # 查询 MySQL 版本，验证连接和 SQL 执行都正常
            cursor.execute("SELECT VERSION() AS version")
            result = cursor.fetchone()
            print("MySQL 版本：", result["version"])

    except Exception as e:
        print("MySQL 连接失败：", e)
    finally:
        if connection:
            connection.close()
            print("MySQL 连接已关闭")


if __name__ == "__main__":
    # 直接运行这个文件时，可以快速验证当前配置是否正确
    test_mysql_connection()
