# 催收场景 AI 质检系统 - 项目概述

## 1. 项目背景

银行信用卡催收部门每天产生数千通电话录音，传统质检依赖人工抽检，覆盖率不足 **5%**，单通 15 分钟通话的完整复核耗时超过 **30 分钟**。本项目探索利用 ASR + 大模型技术，实现录音自动转写、智能小结与质检评分的全链路自动化。

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                       前端演示层                              │
│    原始 HTML 版    +    Vue.js 版（4 角色视图）               │
│    坐席 / 主管 / 分析师 / 管理员                             │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / JSON
┌──────────────────────────▼──────────────────────────────────┐
│                      API 服务层 (Flask)                       │
│   POST /api/upload_audio  POST /api/analyze                  │
│   POST /api/generate_summary  POST /api/generate_qc          │
│   GET  /api/cases  GET /api/cases/<case_id>                  │
│   GET  /api/health                                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────────┐
         ▼                 ▼                     ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   音频处理管线    │ │   LLM 分析服务   │ │   持久化层      │
│                 │ │                 │ │                 │
│ • M4A→WAV 转码  │ │ • DeepSeek V3.2 │ │ • MySQL (数据)  │
│ • FunASR 语音识别│ │ • 智能小结生成   │ │ • 阿里云 OSS    │
│ • CAM++ 说话人分离│ │ • 质检评分      │ │   (音频存储)    │
│ • emotion2vec    │ │                 │ │                 │
│   情感识别       │ │                 │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## 3. 技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| 后端框架 | Python Flask | 7 个 RESTful API 端点，CORS 跨域，200MB 文件限制 |
| 语音识别 | FunASR Paraformer-zh | 中文 ASR，WER < 5%（官方数据） |
| 说话人分离 | CAM++ (FunASR) | 单声道录音说话人聚类，DER < 10% |
| 情感识别 | emotion2vec_plus_large | 支持 9 类情绪识别 |
| 大模型 | DeepSeek V3.2 (via OpenRouter) | 智能小结 + 质检评分，temperature=0.3 |
| 数据库 | MySQL (PyMySQL + DictCursor) | JSON 长文本字段，REPLACE INTO 幂等写入 |
| 对象存储 | 阿里云 OSS | 按日期/分类三级目录组织，签名 URL 临时访问 |
| 前端 | 原生 HTML/JS + Vue.js 单页版 | 多角色视图、情绪时间轴、质检报告可视化 |

## 4. 核心功能模块

### 4.1 音频处理流水线 (`audio_pipeline_service.py`)

5 个处理阶段的自动化串联：

```
输入音频 ──→ [格式转换] ──→ [ASR + 说话人分离] ──→ [情感识别] ──→ [LLM 分析] ──→ [落库] ──→ 输出结构化结果
         16kHz WAV      paraformer+cam++     emotion2vec       DeepSeek       MySQL+OSS
```

- 批处理脚本（`process_audio.py`）和 Web API 共享同一套 `process_audio_file()` 核心逻辑
- 处理完成后同时写入 MySQL 数据库、阿里云 OSS、本地调试文件（JSON + JS）

### 4.2 LLM 分析服务 (`analysis_service.py`)

通过 DeepSeek V3.2 大模型实现两类分析：

**智能小结** — 输出 3 类 11 项结构化标签：

| 类别 | 标签项 |
|------|--------|
| 联系结果类 | 通话状态、承诺还款、还款金额、还款日期 |
| 客户画像类 | 还款意愿、经济状况、协商态度、投诉倾向 |
| 行动项 | 下次联系时间、待办事项、风险等级 |

**质检评分** — 5 条规则自动扣分（满分 100 分）：

| 规则 | 名称 | 扣分 |
|------|------|------|
| R001 | 身份确认 | 10 |
| R002 | 禁止威胁恐吓 | 30 |
| R003 | 录音告知 | 10 |
| R004 | 礼貌用语 | 5 |
| R005 | 情绪控制 | 10 |

### 4.3 API 服务 (`api_server.py`)

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/upload_audio` | 上传音频 + 全自动处理 |
| GET | `/api/cases` | 案件列表（含 OSS 签名 URL 刷新） |
| GET | `/api/cases/<case_id>` | 案件详情 |
| POST | `/api/generate_summary` | 仅生成智能小结 |
| POST | `/api/generate_qc` | 仅生成质检报告 |
| POST | `/api/analyze` | 一次性生成小结+质检 |

### 4.4 数据持久化 (`mysql_storage.py` + `oss_utils.py`)

- **MySQL**：`qc_cases` 表自动建表，`transcript_json` / `emotion_timeline_json` / `summary_json` / `qc_report_json` 四个 LONGTEXT JSON 字段
- **幂等覆盖**：`REPLACE INTO` 确保同一 caseId 重复处理时直接替换
- **OSS 存储**：路径格式 `debt-qc/audio/{category}/{YYYY}/{MM}/{DD}/{filename}`，签名 URL 默认 1 小时有效期

## 5. 项目结构

```
/客服质检小结
├── readme_cn.md                  # 本文档
├── README.md                     # 英文原版说明
├── .env                          # API Key 和数据库配置
├── process_audio.py              # 离线批处理脚本
├── api_server.py                 # Flask API 服务（7 端点）
├── audio_pipeline_service.py     # 音频处理管线核心逻辑
├── analysis_service.py           # LLM 分析服务（小结+质检）
├── mysql_storage.py              # MySQL 存储层
├── oss_utils.py                  # 阿里云 OSS 工具
├── ffmpeg_utils.py               # FFmpeg 封装
├── realtime_asr_demo.py          # 实时 ASR Gradio 演示
│
├── audio/                        # 原始音频输入
├── processed/                    # 处理后 WAV 及 JSON
├── uploads/                      # API 上传临时存储
├── data/                         # 前端演示数据 JS 文件
│
├── 催收质检.html                  # 原生 HTML 前端
├── 催收质检_vue版.html            # Vue.js 前端
├── 前端迭代计划.md                # 前端后续规划
├── Vue前端学习说明.md             # Vue 学习笔记
├── OSS_MySQL_接入说明.md          # OSS+MySQL 配置文档
└── 基于FunASR与LLM的催收质检与智能小结.pdf  # 方案介绍
```

## 6. 量化指标

| 指标 | 数值 |
|------|------|
| API 端点 | **7** 个（6 业务 + 1 健康检查） |
| 处理阶段 | **5** 步（转码→ASR→情感→LLM→落库） |
| 智能小结标签 | **3 类 11 项**结构化输出 |
| 质检规则 | **5 条**自动扣分评分 |
| 模型数 | **4 个**开源模型（Paraformer + CAM++ + VAD + 标点恢复）+ 1 个大模型 API |
| 情感识别 | 支持 **9 类**情绪（愤怒/厌恶/恐惧/快乐/中性/难过/惊讶等） |
| 前端角色视图 | **4 类**（坐席/主管/分析师/管理员） |
| 音频文件限制 | **200MB** 单文件 |
| 单通分析耗时 | **分钟级**（人工复核需 30 分钟以上） |
| 模块数 | **5 个**独立后端模块，解耦可复用 |

## 7. 运行方式

```bash
# 离线批处理
python process_audio.py

# 启动 API 服务（端口 5001）
python api_server.py

# 启动静态文件服务（端口 8080）
python -m http.server 8080

# 实时 ASR 演示
python realtime_asr_demo.py
```

> **注意**：需在 `.env` 中配置 `openrouter_api_key`，如需 OSS 和 MySQL 需额外配置对应环境变量。

## 8. 当前限制与后续方向

- **离线处理**：当前为录音完成后批量处理，可升级为 `paraformer-zh-streaming` 实现实时流式识别
- **单声道录音**：当前使用 CAM++ 做说话人分离（精度受限于算法），生产环境建议升级为双声道录音方案
- **规则硬编码**：质检规则写在 Prompt 模板中，后续可改造为结构化规则库 + RAG 检索
- **无状态**：当前每次请求独立调用 LLM，缺乏历史记忆和上下文积累

## 9. 协议说明

本项目仅用于技术演示和学习交流，音频样本来自公开网络，不涉及真实客户数据。
