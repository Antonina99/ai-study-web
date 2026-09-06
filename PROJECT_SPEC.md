# 项目架构与设计规范书 (PROJECT_SPEC.md)

> **AI 助手须知**：
> 在开始任何代码编写或修改之前，请完整阅读本规范。
> 1. 本文档为项目的核心架构定义，**未经用户明确授权，禁止修改本文档中的技术栈与核心架构设计**。
> 2. 生成的所有代码必须严格遵循本文档定义的目录结构与设计模式。

---

## 1. 项目概述 (Project Overview)

* **项目名称**：AI 大模型实战求职学习平台（智能学习与知识看板）
* **项目定位**：基于 Streamlit 的课程智能学习平台，将「课程原文及导读」文件夹中的 docx 课程逐字稿解析为结构化知识，围绕 5 大求职方向提供课程导读、AI 实战出题刷题、AI 助教问答与错题复习的一体化学习闭环。
* **核心业务逻辑**：
  * 解析 docx 课程原文/导读：用 zipfile + 正则提取段落，按时间戳分段、口语去噪、课程名归一化，增量缓存到 `_knowledge_cache.json`（零第三方依赖）
  * 调用大模型 API 生成课程资产：结构化萃取（关键词/摘要/考点/干货正文）、AI 实战出题、错题深度解析、带原文依据的 AI 助教问答（OpenAI 兼容协议，DeepSeek / 通义千问）；可折叠知识图谱由岗位重点课程映射和当前课程结构化资产离线生成
  * 在学习看板中闭环：模块 → 课程 → 章节三级目录 → 智能自测与刷题（AI 出题优先 + 内置题库离线兜底）→ 错题本记录与重刷 → 错题 JSON 导出与学习进度看板

---

## 2. 核心技术栈 (Tech Stack)

> **AI 约束**：禁止自行替换现有的核心依赖或引入功能重叠的第三方库。本项目依赖保持精简；新增依赖前必须确认现有能力无法满足并取得用户授权。

| 模块/层级 | 技术选型 | 版本/规范要求 | 说明/用途 |
| :--- | :--- | :--- | :--- |
| **前端/UI 框架** | Streamlit + streamlit-shadcn-ui | `streamlit>=1.60`、`streamlit-shadcn-ui>=1.0,<2` | 纯 Python 声明式渲染；Shadcn 用于导航、标签、指标卡和进度组件，无 Node/npm 构建链 |
| **后端框架** | Python + Streamlit 应用 | Python 3.10+ | 单机 Web 应用，无独立 HTTP API 层；`app.py` 为入口，`core/` 承载业务逻辑 |
| **大模型接入** | openai SDK（OpenAI 兼容协议） | `openai>=1.30` | 统一 `core/llm.py` 出口：DeepSeek（deepseek-chat）/ 通义千问（qwen-plus） |
| **数据处理** | Python 标准库 | zipfile + re + json | docx 解析、时间戳分段、口语去噪、归一化匹配，禁止引入 python-docx/pandas 等 |
| **数据库/持久化** | 无 SQLite；JSON 缓存 | `_knowledge_cache.json` | docx 解析结果缓存（运行时自动重建）；学习进度/错题本仅存 Streamlit Session State（会话内有效），不落盘 |
| **测试/诊断** | Python 标准库 `unittest` | `tests/test_*.py` | 使用临时资料和模拟模型结果；不调用真实 API，不修改课程源文件或正式缓存 |

---

## 3. 项目目录结构与模块职责 (Directory Structure)

> **AI 约束**：新建文件时必须严格按照以下结构归类，不得在根目录下随意创建杂乱的文件。

```text
ai_study_web/
├── PROJECT_SPEC.md            # [静态] 项目架构与技术规范（本文档）
├── CODEBUDDY.md               # [静态] 项目 AI 协作规则（勿删）
├── DEPLOY.md                  # [静态] 部署指南
├── requirements.txt           # 依赖清单（streamlit / openai）
├── assets/styles.css          # 工作台全局视觉样式
├── docs/
│   └── course_content_status.md # 真实课程文字入库与验收状态
├── app.py                     # [入口] 应用启动：Session 初始化 / 侧边栏 / Tab 调度
├── kb.py                      # [兼容层] 转发到 core/kb.py（仅历史脚本使用，勿新增依赖）
├── core/                      # 业务核心层（不含 UI，可独立测试）
│   ├── __init__.py
│   ├── llm.py                 # LLM API 层：同步/流式调用、超时重试、JSON 解析、System Prompt 常量、错误中文化
│   ├── data.py                # 数据与业务层：求职方向/课程大纲/离线题库、课程索引、知识库加载、课程资产组装、出题逻辑、题目工具
│   └── kb.py                  # 知识库层：docx 解析、时间戳分段、口语去噪、课程名归一化、增量缓存、离线规则出题、LLM 上下文拼接
├── views/                     # UI 渲染层（只负责展示与交互，逻辑委托 core/）
│   ├── __init__.py
│   ├── tab1_course.py         # Tab1 课程大纲与导读（三级级联 + 详情看板 + 课程内测评）
│   ├── tab2_quiz.py           # Tab2 智能自测与刷题（AI 出题 + 离线兜底 + 结构化解析）
│   ├── tab3_assistant.py      # Tab3 课程 AI 助教（课程引用校验 + 知识对话）
│   ├── tab4_review.py         # Tab4 错题复习（错题展示 + JSON 导出 + 重刷）
│   └── workspace_ui.py        # 工作台主题、导航、标签、指标卡与进度组件
├── tests/                     # 标准库 unittest 回归测试（临时数据，不调用真实 API）
│   ├── __init__.py
│   ├── test_course_index.py   # 课程名绑定、AI 分类兜底与选项清洗
│   ├── test_real_course_inventory.py # 已绑定真实课程端到端验收
│   ├── test_text_learning.py  # 转写、清洗去重、知识图谱、章节范围、判分与降级链路
├── 课程原文及导读/            # [数据源] 课程 docx（命名规则：课程名_原文 / 课程名_导读）
└── _knowledge_cache.json      # [运行时生成] docx 解析缓存（勿手动维护）
```

---

## 4. 架构设计模式与边界约定 (Architecture Rules)

1. **分层隔离原则**：
   * **UI 层（`views/` + `app.py`）**：只负责 Streamlit 组件渲染与用户交互，禁止直接写复杂业务逻辑（如出题规则、docx 解析、JSON 解析）；业务一律调用 `core/` 层函数。
   * **业务层（`core/data.py`、`core/kb.py`）**：统一处理知识库解析、课程资产组装、出题与判分逻辑。
   * **LLM 出口层（`core/llm.py`）**：全项目**唯一**调用大模型 API 的模块，禁止在 `views/` 或 `app.py` 中直接创建 openai client 或发起 API 请求。
   * **纯函数/工具层**：去噪、归一化、选项洗牌等工具函数保持无状态（纯函数）。

2. **状态管理约定**：
   * 所有会话状态统一在 `app.py::init_session_state()` 中声明默认值并注入 `st.session_state`，禁止在 `views/` 内直接新增未声明的状态键（运行期键除外，如 `ans_*` / `cans_*` / `ai_explain_*`）。
   * `cleaned_cache` 课程萃取结果存于 Session State，键必须包含课程源指纹，避免切换课程后串用结果；可折叠知识树由当前课程资产即时组装，不单独缓存。
   * 学习进度（`completed_chapters`）与错题本（`error_notebook`）**只存会话、不落盘**，如需持久化须先与用户确认方案。

3. **AI 能力与降级约束（本项目的核心设计模式）**：
   * 可降级能力遵守「**AI 优先 + 离线规则兜底**」双模架构：未配置 API Key 或 LLM 调用失败时，课程整理、知识图谱和测评自动降级为规则或内置题库；AI 助教需要有效 API Key，原文阅读、检索与离线学习链路不受影响。
   * 出题链路失败逐级回退：AI 实战出题（`data.generate_practical_quiz`）→ 离线题库（`data.fallback_questions`）。
   * 题库/题目选项展示前必须经 `data.shuffle_question()` 洗牌，禁止固定正确项位置。

4. **错误处理机制**：
   * 本项目为单机 Streamlit 应用，**无独立后端 HTTP API**，不适用 `{code, message, data}` 统一返回格式。
   * LLM 层异常统一经 `core/llm.py::humanize_error()` 翻译为友好中文提示后抛给 UI 层展示；业务层函数对 LLM 异常采用 try/except 捕获并触发离线降级，不允许裸异常冒泡到页面崩溃。
   * Streamlit 组件兼容采用「特性检测 + try/except 回退」（如 `st.tags` 不可用时回退 Markdown 胶囊）。

5. **数据源约定**：
   * 课程知识库唯一数据源为 `课程原文及导读/` 下的 docx 文件，命名必须遵循「课程名_原文.docx / 课程名_导读.docx」，放入目录刷新页面即可自动发现新课程（增量指纹检测）。
   * 解析缓存 `_knowledge_cache.json` 由 `core/kb.py` 自动维护，禁止手工编辑；部署时可不提交，首次访问自动重建。

---

## 5. 环境配置与启动指令 (Environment & Run Scripts)

* **环境变量依赖**：
  * 本项目**无环境变量依赖**。API Key 由用户在页面侧边栏「API 设置」中手动填写，仅存于会话内存，不入库、不写环境变量。（如后续需服务器统一配置，可改为优先读取 `OPENAI_API_KEY` 环境变量，但需与用户确认。）

* **基础运行指令**：
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动开发环境
streamlit run app.py
# 本地访问：http://localhost:8501

# 3. 对外部署（详见 DEPLOY.md，0.0.0.0 必须指定）
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

* **数据准备**：将必需的 `课程名_原文.docx` 和可选的 `课程名_导读.docx` 放入 `课程原文及导读/`，首次访问自动解析并生成缓存；未配置 API Key 时仍可阅读、检索原文并使用离线测评，AI 助教需配置 Key。
