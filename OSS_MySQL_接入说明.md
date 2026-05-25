# OSS 与 MySQL 接入说明

本文档说明本次代码改造做了什么、为什么这样改，以及你后续应该怎么配。

---

## 1. 改造目标

本次改造把原来的本地文件存储方式拆成两部分：

1. 音频文件存到阿里云 OSS
2. 结构化分析结果存到 MySQL

这样做的好处是：

1. OSS 适合存大文件，比如原始音频和转码后的 WAV
2. MySQL 适合存结构化数据，比如 transcript、summary、qcReport
3. 后续前端查记录时，不需要扫描本地目录，直接查数据库即可

---

## 2. 本次新增了哪些文件

### 2.1 `analysis_service.py`

作用：

1. 把原来 `api_server.py` 里的 LLM 分析逻辑单独抽出来
2. 让 `api_server.py` 和 `process_audio.py` 共用同一套分析逻辑

核心函数：

```python
generate_summary(transcript)
generate_qc_report(transcript)
analyze_transcript(transcript)
```

---

### 2.2 `oss_utils.py`

作用：

1. 负责读取 OSS 配置
2. 负责上传原始音频和 WAV 音频到 OSS
3. 返回 `object_key` 和 `signed_url`

核心函数：

```python
upload_file_to_oss(file_path, category)
```

---

### 2.3 `mysql_storage.py`

作用：

1. 负责连接 MySQL
2. 自动初始化表结构
3. 把分析结果写入 `qc_cases` 表

核心函数：

```python
init_mysql_tables()
save_case_record(record)
```

---

### 2.4 `.env.oss_mysql.example`

作用：

1. 给你看完整的环境变量该怎么配
2. 包含 OpenRouter、MySQL、OSS 三类配置

---

### 2.5 `mysql_schema.sql`

作用：

1. 单独给出建表 SQL
2. 方便你手动建表，或者交给 DBA 执行

---

## 3. 修改前后的流程对比

### 3.1 修改前

原流程：

```text
audio/*.m4a
   ↓
process_audio.py
   ↓
本地转成 processed/*.wav
   ↓
本地生成 transcript.json
   ↓
本地生成 demo_data_xxx.js
```

问题：

1. 音频只在本地，换机器就没了
2. 结果没有入库，后续不好查询
3. `api_server.py` 和 `process_audio.py` 无法复用 LLM 分析逻辑

---

### 3.2 修改后

现在流程：

```text
audio/*.m4a
   ↓
process_audio.py
   ↓
转成 processed/*.wav
   ↓
上传原始音频到 OSS
   ↓
上传 WAV 音频到 OSS
   ↓
调用 LLM 生成 summary + qcReport
   ↓
保存 transcript / emotion / summary / qcReport 到 MySQL
   ↓
保留本地 demo_data_xxx.js 方便前端调试
```

这样就变成：

1. 大文件在 OSS
2. 结构化数据在 MySQL
3. 本地文件只是辅助调试，不再是唯一数据源

---

## 4. 代码修改前后对比

## 4.1 `api_server.py` 修改前

之前 `api_server.py` 里自己包含了：

1. Prompt
2. `call_llm`
3. `extract_json_from_response`
4. `format_transcript`

也就是说，接口文件里既处理路由，又处理分析逻辑，耦合比较重。

示意代码：

```python
def call_llm(prompt: str) -> str:
    response = requests.post(...)
    return result["choices"][0]["message"]["content"]


def extract_json_from_response(response: str) -> dict:
    ...


@app.route("/api/generate_summary", methods=["POST"])
def generate_summary():
    prompt = SUMMARY_PROMPT_TEMPLATE.format(...)
    response = call_llm(prompt)
    summary = extract_json_from_response(response)
```

### 4.2 `api_server.py` 修改后

现在改成直接调用公共分析服务：

```python
from analysis_service import MODEL_NAME, analyze_transcript, generate_qc_report, generate_summary


@app.route("/api/generate_summary", methods=["POST"])
def generate_summary():
    summary = generate_summary(transcript)
```

好处：

1. `api_server.py` 只保留接口职责
2. 分析逻辑集中到 `analysis_service.py`
3. `process_audio.py` 也能直接复用

---

## 4.3 `process_audio.py` 修改前

之前处理完音频以后，只做了本地写文件：

```python
js_output_path = PROJECT_ROOT / f"demo_data_{base_name}.js"
final_data = generate_demo_data_js(...)

json_output_path = output_dir / f"{base_name}_transcript.json"
with open(json_output_path, "w", encoding="utf-8") as f:
    json.dump(transcript, f, ensure_ascii=False, indent=2)
```

问题：

1. 没有上传 OSS
2. 没有入 MySQL
3. `summary` 和 `qcReport` 仍然是占位值

---

## 4.4 `process_audio.py` 修改后

现在新增了 3 段关键逻辑：

### 第一段：上传音频到 OSS

```python
original_audio_oss = upload_file_to_oss(input_path, "original")
wav_audio_oss = upload_file_to_oss(wav_path, "wav")
```

说明：

1. `input_path` 是原始音频
2. `wav_path` 是转码后的 WAV 音频
3. 上传成功后会得到 OSS 地址

---

### 第二段：调用 LLM 生成真实分析结果

```python
analysis_result = analyze_transcript(transcript)
summary = analysis_result["summary"]
qc_report = analysis_result["qcReport"]
```

说明：

1. 不再写死占位的 `summary`
2. 不再写死 `score = 0`
3. 现在会生成真实的小结和质检结果

---

### 第三段：把结果保存到 MySQL

```python
save_case_record({
    "case_id": case_id,
    "audio_file_name": input_path.name,
    "original_audio_url": original_audio_oss["signed_url"],
    "wav_audio_url": wav_audio_oss["signed_url"],
    "duration_seconds": duration,
    "transcript": transcript,
    "emotion_timeline": emotion_timeline,
    "summary": summary,
    "qc_report": qc_report
})
```

说明：

1. 音频地址存数据库
2. transcript 存数据库
3. emotionTimeline 存数据库
4. summary 存数据库
5. qcReport 存数据库

---

## 5. 新增表结构说明

表名：

```sql
qc_cases
```

主要字段说明：

1. `case_id`
   用来标识一次通话案件

2. `audio_file_name`
   原始音频文件名

3. `original_audio_url`
   原始音频上传到 OSS 后的地址

4. `wav_audio_url`
   转码后的 WAV 音频地址

5. `duration_seconds`
   音频时长

6. `transcript_json`
   ASR 识别结果

7. `emotion_timeline_json`
   情感时间轴

8. `summary_json`
   智能小结

9. `qc_report_json`
   质检报告

---

## 6. 配置项怎么填

你需要准备一个 `.env`，至少包含下面这些配置：

```env
openrouter_api_key=你的_openrouter_api_key
model_name=deepseek/deepseek-v3.2

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=123456
MYSQL_DATABASE=debt_qc
MYSQL_CHARSET=utf8mb4
MYSQL_AUTOCOMMIT=true
MYSQL_CONNECT_TIMEOUT=10

OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET_NAME=your-bucket-name
OSS_ACCESS_KEY_ID=your-access-key-id
OSS_ACCESS_KEY_SECRET=your-access-key-secret
OSS_URL_EXPIRE_SECONDS=3600
OSS_AUDIO_PREFIX=debt-qc/audio
```

你也可以直接参考：

- [.env.oss_mysql.example](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/.env.oss_mysql.example:1)

---

## 7. 代码里的中文注释重点说明

本次新增代码里，我已经把关键位置都写了中文注释，重点包括：

1. 为什么要把 LLM 逻辑抽成公共服务
2. 为什么音频适合存 OSS
3. 为什么 transcript / summary / qcReport 适合存 MySQL
4. 为什么要保留本地 `demo_data_xxx.js`
5. 每个核心函数的输入输出是什么

建议你优先看这些文件：

1. [analysis_service.py](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/analysis_service.py:1)
2. [oss_utils.py](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/oss_utils.py:1)
3. [mysql_storage.py](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/mysql_storage.py:1)
4. [process_audio.py](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/process_audio.py:1)

---

## 8. 你现在怎么用

### 第一步：安装依赖

```bash
pip install pymysql python-dotenv oss2 requests flask flask-cors pydub
```

如果你还要跑 ASR 和情感识别，也需要：

```bash
pip install funasr torch torchaudio modelscope
```

---

### 第二步：创建 MySQL 数据库

先创建数据库：

```sql
CREATE DATABASE debt_qc DEFAULT CHARSET utf8mb4;
```

然后执行：

- [mysql_schema.sql](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/mysql_schema.sql:1)

或者直接运行脚本时，让代码自动建表。

---

### 第三步：配置 `.env`

把 `.env.oss_mysql.example` 的内容复制到你自己的 `.env`，再改成真实配置。

---

### 第四步：执行处理脚本

```bash
python process_audio.py
```

执行后会完成：

1. 音频转 WAV
2. ASR 识别
3. 说话人映射
4. 情感识别
5. 音频上传 OSS
6. LLM 生成小结和质检
7. 结果保存 MySQL
8. 本地保留调试文件

---

## 9. 当前需要你注意的点

### 9.1 现在保存的是签名 URL

当前代码存的是：

```python
original_audio_oss["signed_url"]
wav_audio_oss["signed_url"]
```

这适合开发测试，因为你能直接打开验证。

但生产环境通常建议存：

1. `bucket_name`
2. `object_key`
3. 必要时再动态生成签名 URL

原因是签名 URL 会过期。

---

### 9.2 `REPLACE INTO` 会覆盖同一个 `case_id`

当前 MySQL 保存逻辑使用的是：

```sql
REPLACE INTO qc_cases ...
```

意思是：

1. 如果 `case_id` 已存在，就覆盖
2. 如果不存在，就插入

这适合开发阶段反复调试。

如果你后面要做正式审计留痕，建议改成：

1. `INSERT`
2. 单独记录版本号
3. 或者增加历史表

---

## 10. 本次最核心的变化总结

你可以把这次改造理解成三句话：

1. `api_server.py` 不再自己写分析逻辑，而是调用 `analysis_service.py`
2. `process_audio.py` 不再只写本地文件，而是多了 OSS 上传和 MySQL 入库
3. 数据存储从“纯本地调试”升级成“对象存储 + 结构化数据库”的常见生产化方案
