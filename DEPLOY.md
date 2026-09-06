# 部署与课程文字入库指南

本项目是 Python + Streamlit 动态应用。音视频在项目外转换成文字，项目只接收课程文字 DOCX，并围绕文字提供阅读、整理、问答和测评。

## 1. 运行要求

- Python 3.10 或更高版本
- 项目根目录中的 `requirements.txt`
- 课程资料目录 `课程原文及导读/`
- 可选的大模型 API Key；不填写时阅读、原文检索和离线测评仍可使用

项目没有 SQLite 数据库。学习进度、当前答题状态和错题本保存在 Streamlit Session State 中，刷新页面、关闭会话或服务重启后会清空；错题可在页面导出 JSON。`_knowledge_cache.json` 只缓存 DOCX 解析结果，可删除并自动重建。

## 2. 本地启动

### Windows PowerShell

```powershell
cd D:\AI项目\ai_study_web
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

浏览器访问 `http://127.0.0.1:8501/`。

### Linux / macOS

```bash
cd /path/to/ai_study_web
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

需要从局域网或服务器外部访问时使用：

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

启动后可运行回归测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 3. 导入一门课程

### 3.1 文件命名

将文件放到项目根目录的 `课程原文及导读/`：

```text
课程名称_原文.docx       # 必需
课程名称_导读.docx       # 可选
```

例如：

```text
RAG技术与应用_原文.docx
RAG技术与应用_导读.docx
```

文件名中的课程名称应与课程大纲名称一致。开头可以带序号，如 `2、RAG技术与应用_原文.docx`；系统会在匹配时去除常见序号、空格和全半角标点差异。无法匹配大纲的课程会进入“新增课程（自动发现）”模块，不会丢弃。

### 3.2 只有转写原文

导读不是必需文件。只有 `_原文.docx` 时，系统会：

- 解析时间戳并生成章节/片段目录；
- 没有时间戳时按 DOCX 正文段落生成 `original-1`、`original-2` 等稳定标识；
- 使用规则清洗生成可阅读正文；
- 支持原文搜索、课程问答上下文和离线课程测评。

原文 DOCX 建议结构：

```text
RAG技术与应用_原文
2026年09月06日
00:05
今天介绍 RAG 的文档切分策略。
01:20
接下来介绍召回和重排。
```

时间戳和正文也可以位于同一段：

```text
00:05 今天介绍 RAG 的文档切分策略。
发言人 1 01:20 接下来介绍召回和重排。
```

### 3.3 支持的时间戳

支持半角或全角冒号：

- `MM:SS`，例如 `07:59`、`60:00`
- `HH:MM:SS`，例如 `01:02:03`
- 可选说话人前缀，例如 `发言人 1 00:05`、`说话人 A 00：05`、`讲师 01:02:03`

时间戳只用于文字分段、章节范围和引用定位，不用于音视频播放。没有时间戳时正文仍能入库。

### 3.4 可选导读格式

导读解析依赖以下三个标记行，文字必须保持一致：

```text
RAG技术与应用_导读
2026年09月06日
关键词
RAG 向量检索 重排
全文摘要
本课程介绍企业知识库的完整处理流程。
章节速览
00:00 文档切分
介绍切分粒度与语义完整性。
10:30 召回与重排
介绍召回、过滤和重排策略。
```

导读的第二段应保留日期或其他元数据占位，因为解析器从第三段开始识别标记。章节时间戳应能对应原文范围；一个章节覆盖本章起点到下一章起点之前的原文，最后一章覆盖到课程结尾。

### 3.5 让新文件生效

文件放入目录后刷新网页。应用会按文件名、大小和修改时间检测变化并更新 `_knowledge_cache.json`。正常结果包括：

1. 侧边栏“知识库覆盖”数量增加；
2. 课程目录显示“课程文字已入库”；
3. 课程页可以阅读章节并搜索原文；
4. 无 API Key 时也能生成课程文字题。

资料盘点与当前缺口见 `docs/course_content_status.md`。

## 4. 常见问题排查

### 页面找不到新课程

1. 确认文件扩展名是 `.docx`，不是 `.doc`、TXT 或伪装扩展名。
2. 确认文件位于 `课程原文及导读/` 根层，没有放进子目录。
3. 确认文件名以 `_原文.docx` 或 `_导读.docx` 结尾。
4. 刷新页面；仍无效时停止服务，删除 `_knowledge_cache.json` 后重新启动。
5. 查看终端是否有 DOCX 损坏或权限错误。

### 课程存在但没有正文

- 原文文件第一段应为标题；第二段可以是日期，正文放在其后。
- 确认 DOCX 中的文字是可选择的普通段落，不是截图或扫描图片。
- 空原文会保留课程记录并显示无可阅读文字，不会编造内容。

### 章节范围不正确

- 检查时间戳是否是有效的 `MM:SS` 或 `HH:MM:SS`。
- 分钟和秒的末两位必须小于 60；`60:00` 表示 60 分钟，是有效格式。
- 导读章节时间戳应按课程顺序排列，并与原文使用同一时间基准。

### 导读没有关键词或章节

- 确认标记行严格写为“关键词”“全文摘要”“章节速览”。
- 确认导读第二段有日期或占位内容。
- 导读缺失不会阻止原文阅读；可以先只导入原文。

### AI 功能不可用

- API Key 由每位用户在侧边栏输入，只保存在当前会话内存中，项目不会写入文件或环境变量。
- 确认所选模型与 API Key 服务商匹配。
- API 失败时课程测评会自动降级；AI 助教本身需要有效 API Key。

## 5. Streamlit Community Cloud

1. 将代码、`requirements.txt` 和需要公开使用的课程 DOCX 推送到 Git 仓库。
2. 不提交 `.venv/`、`__pycache__/` 和 `_knowledge_cache.json`。
3. 在 Streamlit Community Cloud 创建应用，入口文件选择 `app.py`。
4. 部署完成后打开应用，检查知识库覆盖、课程阅读和离线测评。

课程 DOCX 会随仓库一起部署。包含私密或无权公开的转写文字时，不应放进公开仓库；应使用私有仓库或自管服务器，并按实际授权控制访问。

应用没有课程级分享链接或“对外分享”侧边栏。部署平台提供的应用 URL 就是访问地址。

## 6. Linux 云服务器

示例目录为 `/opt/ai_study_web`：

```bash
cd /opt/ai_study_web
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

在云安全组和系统防火墙中放行实际使用的端口。长期运行可配置 systemd；使用域名时可通过 Nginx 反向代理到 `127.0.0.1:8501` 并配置 HTTPS。

当前没有数据库持久化需求。需要更新课程时替换或增加 `课程原文及导读/*.docx`，然后重启或刷新应用。

## 7. 临时内网穿透

先在本机保持 Streamlit 运行，再让 ngrok、cpolar 或 frp 转发本机 8501 端口。外部访问地址由穿透工具提供。临时地址、访问控制和流量限制以所用工具为准，项目页面内无需填写分享地址。

## 8. `.gitignore` 建议

```gitignore
.venv/
__pycache__/
*.pyc
.vscode/
.idea/

# DOCX 解析缓存会自动重建
_knowledge_cache.json
```

是否提交 `课程原文及导读/` 取决于部署方式和资料授权。部署环境若没有这些文件，课程大纲仍会显示，但对应课程会标记为尚未入库。
