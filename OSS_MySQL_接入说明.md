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

---

## 11. 第二轮补充改造：查询 API 和前端联动

你这次追加的需求是：

1. 增加“查询历史案件”的 API
2. 前端页面不要再主要依赖本地 `demo_data_xxx.js`
3. 要以“正常能跑通”为前提

所以我继续做了下面这些补充。

---

## 12. 新增查询 API

### 12.1 查询案件列表

接口：

```text
GET /api/cases
```

作用：

1. 查询数据库中的历史案件
2. 按更新时间倒序返回
3. 返回前端可以直接渲染的结构

你也可以带参数：

```text
GET /api/cases?limit=100
```

---

### 12.2 查询单个案件详情

接口：

```text
GET /api/cases/<case_id>
```

作用：

1. 查询单条案件详情
2. 返回 transcript、summary、qcReport、emotionTimeline
3. 同时刷新一次 OSS 的签名 URL，避免前端拿到过期音频地址

---

## 13. 查询 API 修改前后对比

### 修改前

之前后端只有这些接口：

```text
GET  /api/health
POST /api/generate_summary
POST /api/generate_qc
POST /api/analyze
```

问题：

1. 只能做“分析”
2. 不能查历史案件
3. 前端无法直接读取数据库中的案件

---

### 修改后

现在增加了：

```text
GET /api/cases
GET /api/cases/<case_id>
```

并且在接口里做了两件重要的事：

1. 把数据库记录整理成前端需要的结构
2. 对 OSS `object_key` 重新生成签名 URL

这样前端就不需要自己拼数据结构了。

---

## 14. 前端页面修改前后对比

### 14.1 修改前

原页面主要依赖：

```html
<script src="./data/demo_data_audio1.js"></script>
<script src="./data/demo_data_audio2.js"></script>
```

并且音频路径写死为：

```javascript
const AUDIO_FILE_MAP = {
    'real_audio1': './processed/audio1.wav',
    'real_audio2': './processed/audio2.wav'
}
```

问题：

1. 页面强依赖本地生成的 JS 文件
2. 音频强依赖本地 `processed/*.wav`
3. 数据库里的历史案件无法直接显示

---

### 14.2 修改后

现在前端改成：

1. 页面启动先请求 `/api/cases`
2. 把数据库中的案件合并到页面数据源
3. 点开案件时，再请求 `/api/cases/<case_id>` 刷新详情
4. 音频播放地址改为后端返回的 `storage.wavAudioUrl`

也就是说，现在页面主要依赖的是：

```text
后端 API + MySQL + OSS
```

而不是：

```text
本地 demo_data.js + 本地 processed.wav
```

---

## 15. 前端关键代码对比

### 15.1 数据来源修改前

之前是：

```javascript
const MOCK_DATA = {
    perfect: ...,
    violation: ...,
    defect: ...,
    real_audio1: GENERATED_DATA_AUDIO1,
    real_audio2: GENERATED_DATA_AUDIO2
}
```

### 15.2 数据来源修改后

现在是：

```javascript
let MOCK_DATA = {
    perfect: ...,
    violation: ...,
    defect: ...
}

await fetchBackendCases();
renderUIForRole('agent');
```

意思是：

1. 本地 mock 只作为兜底示例
2. 真正的案件优先从数据库加载

---

### 15.3 音频加载修改前

之前：

```javascript
const audioPath = AUDIO_FILE_MAP[caseId];
currentState.audioElement = new Audio(audioPath);
```

### 15.4 音频加载修改后

现在：

```javascript
const audioPath = data?.storage?.wavAudioUrl || null;
currentState.audioElement = new Audio(audioPath);
```

意思是：

1. 音频不再依赖本地文件
2. 直接使用 OSS 返回的临时可访问地址

---

## 16. 为了“正常运行”做的额外处理

### 16.1 去掉了前端对空 Gemini Key 的强依赖

原页面里“生成沟通建议”按钮会直接调 Gemini，但代码里：

```javascript
const apiKey = "";
```

这在当前状态下点击必报错，不符合“正常能跑通”的前提。

所以我把这块改成：

1. 不再依赖额外第三方 Key
2. 直接根据 `summary + qcReport + transcript` 生成本地建议文案
3. 至少按钮可正常使用，不会点一下就报错

这属于“先保证跑通，再考虑增强”的处理方式。

---

### 16.2 点开案件时会刷新详情

前端现在不只是启动时拉一次列表，而是：

1. 页面初始化拉案件列表
2. 打开具体案件时再调用一次详情接口

这样做的原因是：

1. OSS 签名 URL 会过期
2. 再查一次能拿到新的 URL
3. 音频播放更稳定

---

## 17. 数据库结构新增字段

为了让 OSS 地址更稳，我补了两个字段：

1. `original_audio_object_key`
2. `wav_audio_object_key`

原因：

1. 只存签名 URL 不够稳，因为会过期
2. 存 `object_key` 后，后端可以临时再签一次新的 URL

所以现在数据库里既存：

1. URL
2. object_key

这样开发调试和后续生产化都兼顾到了。

---

## 18. 现在完整链路是什么

现在完整流程已经变成：

```text
音频文件
  -> process_audio.py
  -> FunASR / emotion2vec
  -> OSS 上传原始音频和 WAV
  -> LLM 生成 summary / qcReport
  -> MySQL 保存案件结果
  -> api_server.py 提供查询接口
  -> 前端页面通过 /api/cases 和 /api/cases/<case_id> 展示案件
```

这就是一条比较完整的“可查询、可展示”的链路。

---

## 19. 现在你应该怎么运行

建议按这个顺序：

### 第一步：确认 `.env`

至少要配：

1. OpenRouter
2. MySQL
3. 阿里云 OSS

参考：

- [.env.oss_mysql.example](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/.env.oss_mysql.example:1)

---

### 第二步：准备 MySQL

1. 创建数据库 `debt_qc`
2. 执行：

- [mysql_schema.sql](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/mysql_schema.sql:1)

---

### 第三步：先跑音频处理脚本

```bash
python process_audio.py
```

目的：

1. 先把音频传 OSS
2. 先把 transcript / summary / qcReport 写进 MySQL

---

### 第四步：启动后端接口

```bash
python api_server.py
```

---

### 第五步：打开前端页面

打开：

- [催收质检.html](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/催收质检.html:1)

页面会优先去请求：

```text
http://localhost:5001/api/cases
```

如果后端没起来，页面会回退到本地 mock 示例数据。

---

## 20. 这轮修改最值得你重点看的文件

1. [api_server.py](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/api_server.py:1)
   这里新增了查询列表、查询详情两个接口

2. [mysql_storage.py](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/mysql_storage.py:1)
   这里新增了列表查询、单条查询、结构格式化

3. [oss_utils.py](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/oss_utils.py:1)
   这里新增了“对已有 object_key 重新签名”的能力

4. [催收质检.html](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/催收质检.html:1)
   这里把页面从“本地数据驱动”改成了“接口驱动优先”

---

## 21. 第三轮补充改造：上传音频并自动处理

这轮你要求的重点是：

1. 前端直接上传音频
2. 后端接收后自动完成处理
3. 先以“正常完成生成上传功能”为主
4. 同时给一个 Vue 页面做对照

所以这轮我把“上传链路”补齐了。

---

## 22. 新增上传 API

新增接口：

```text
POST /api/upload_audio
```

上传字段：

```text
file
```

支持扩展名：

```text
.m4a
.wav
.mp3
.mp4
```

接口流程：

```text
接收文件
 -> 保存到 uploads/
 -> 调用统一音频处理流水线
 -> 转 WAV
 -> ASR + 说话人分离
 -> 情感识别
 -> 上传原始音频和 WAV 到 OSS
 -> 调用 LLM 生成 summary / qcReport
 -> 保存 MySQL
 -> 返回 caseId 和前端展示数据
```

---

## 23. 上传功能代码前后对比

### 修改前

之前只有离线脚本：

```text
python process_audio.py
```

问题：

1. 用户必须先把音频手动放到 `audio/` 目录
2. 必须再手工运行脚本
3. 前端无法直接上传

---

### 修改后

现在新增：

```text
POST /api/upload_audio
```

前端上传后，后端直接处理，不需要手工把文件拷到 `audio/` 目录。

---

## 24. 新增公共流水线服务

新增文件：

- [audio_pipeline_service.py](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/audio_pipeline_service.py:1)

作用：

1. 把“上传接口”和“离线脚本”未来可共用的音频处理链路抽成公共服务
2. 避免后端接口再复制一套处理代码
3. 保证上传 API 产出的结果结构和原脚本一致

这里是这轮改造最关键的代码组织变化。

---

## 25. 原生 HTML 页面新增了什么

文件：

- [催收质检.html](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/催收质检.html:1)

新增内容：

1. 左侧栏新增音频上传区域
2. 可直接选择本地音频文件
3. 点击“上传并处理”后，调用 `/api/upload_audio`
4. 上传完成后自动刷新案件列表
5. 自动打开新生成的案件

也就是说，现在你不需要：

1. 手工把音频复制进 `audio/`
2. 再手工执行处理脚本

现在可以直接在页面完成上传和处理。

---

## 26. Vue 对照页面

新增文件：

- [vue_frontend_demo.html](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/vue_frontend_demo.html:1)

说明：

1. 这是一个 Vue 3 CDN 版对照页面
2. 不依赖本地构建工具
3. 用来对比原生 HTML 页面和 Vue 写法的区别
4. 接口与数据源完全一致，仍然调用：
   - `GET /api/cases`
   - `GET /api/cases/<case_id>`
   - `POST /api/upload_audio`

它的作用主要是：

1. 给你一个“如果后面改成组件化前端，大致会怎么写”的参考
2. 现在就能直接打开看逻辑

不是替代现有页面，而是对照页。

---

## 27. 这轮新增接口的中文注释重点

本轮新增代码里，我补了这些关键注释：

1. `api_server.py`
   说明了上传接口为什么要先校验扩展名

2. `audio_pipeline_service.py`
   说明了为什么要抽公共流水线

3. `催收质检.html`
   说明了上传后为什么要刷新案件详情

4. `vue_frontend_demo.html`
   结构上尽量保持清晰，便于你对比原生写法和 Vue 写法

---

## 28. 现在推荐的运行方式

如果你想验证“上传并自动处理”这条主链路，建议按这个顺序：

### 第一步：确认依赖

至少需要：

```bash
pip install flask flask-cors requests python-dotenv pymysql oss2 pydub werkzeug
```

如果要实际跑 ASR 和情感识别，还需要：

```bash
pip install funasr torch torchaudio modelscope
```

同时你本机要有 `ffmpeg`。

---

### 第二步：确认 `.env`

你必须有：

1. OpenRouter 配置
2. MySQL 配置
3. OSS 配置

参考：

- [.env.oss_mysql.example](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/.env.oss_mysql.example:1)

---

### 第三步：启动后端

```bash
python api_server.py
```

---

### 第四步：打开前端页面

原生页面：

- [催收质检.html](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/催收质检.html:1)

Vue 对照页：

- [vue_frontend_demo.html](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/vue_frontend_demo.html:1)

---

### 第五步：上传音频

在页面里选择文件后点击：

```text
上传并处理
```

处理完成后：

1. OSS 会有音频文件
2. MySQL 会有案件记录
3. 页面会刷新出新案件

---

## 29. 当前还需要你确认的一点

虽然上传 API 和前端入口已经补齐，但是否“完全跑通”还取决于本机实际环境是否满足：

1. `ffmpeg` 能否被 `pydub` 调用
2. FunASR / emotion2vec 模型是否能正常加载
3. OpenRouter Key 是否有效
4. OSS / MySQL 配置是否真实可用

也就是说，代码链路已经打通，但真实联调仍然依赖你的本地环境配置。

---

## 30. 这轮修改的最核心总结

这轮你可以只记住 4 句话：

1. 现在后端已经支持 `POST /api/upload_audio`
2. 原生 HTML 页面已经能直接上传音频并自动处理
3. 页面会自动刷新新生成的案件
4. 我另外补了一个 [vue_frontend_demo.html](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/vue_frontend_demo.html:1) 供你对照前端实现方式

---

## 31. 第四轮补充：Windows 下固定使用本地 ffmpeg.exe

你后面反馈的报错是：

```text
[WinError 2] 系统找不到指定的文件
```

这个问题的根因是：

1. 你上传的是 MP3
2. `pydub` 在解析 MP3 时要调用 `ffmpeg`
3. Windows 环境里没有从系统 PATH 找到 `ffmpeg`

所以我没有继续让代码依赖系统环境变量，而是直接改成：

1. 优先使用项目目录里的 `ffmpeg.exe`
2. 如果项目目录里还有 `ffprobe.exe`，也一并指定

新增文件：

- [ffmpeg_utils.py](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/ffmpeg_utils.py:1)

对应修改：

- [process_audio.py](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/process_audio.py:1)

这样做的好处是：

1. 不强依赖系统 PATH
2. 对当前这个项目最直接
3. 更适合 Windows 本地演示环境

---

## 32. Vue 页面这次也升级了

之前我给的是一个偏简化的 Vue 对照页。

现在已经换成了更完整、更接近原始页面结构的版本：

- [vue_frontend_demo.html](D:/BaiduNetdiskDownload/测试/笔记/案例12-客服质检小结/vue_frontend_demo.html:1)

它现在包含：

1. 案件列表
2. 上传音频
3. 音频播放
4. 智能小结
5. 质检报告
6. 情绪时间轴
7. 通话转录
8. 重新分析按钮

所以现在它不是简单的“演示页”，而是一个更完整的 Vue 版本前端参考。
