# 部署指南（DEPLOY.md）

本文档说明如何让**不依赖本地网络**的外部用户通过互联网访问本项目。

- 项目本质：**Streamlit 动态 Web 应用**（Python），不是静态站点，需要一个能跑 Python 的运行环境。
- 三个可选方案：
  - **方案 A（推荐，免费、最快）**：Streamlit Community Cloud —— 适合快速公开演示。
  - **方案 B（推荐长期使用）**：国内云服务器（腾讯云 / 阿里云轻量）—— 数据持久、国内访问稳定。
  - **方案 C（临时）**：内网穿透（ngrok / cpolar / frp）—— 不搬服务器，临时对外演示。

---

## 一、项目部署相关知识

| 组成部分 | 说明 |
| --- | --- |
| 运行环境 | 需要 Python 3.9+ 与 `requirements.txt` 中的依赖（`streamlit` / `openai`） |
| 知识库 | `课程原文及导读/*.docx` **必须随代码一起上传**（否则课程数据为空） |
| 解析缓存 | `_knowledge_cache.json`，部署后首次访问会自动重建，无需上传 |
| 本地数据 | `learning_tracker.db`（错题本 / 学习统计 / 分享链接记录），**免费 PaaS 平台可能被重置** |
| AI 能力 | 访客在页面手动填写 API Key（`app.py` 侧边栏「API 设置」）；离线规则兜底，不填也可完整浏览 |

### 启动命令

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

> `--server.address 0.0.0.0` 是**必须的**，否则外部无法访问。

---

## 二、方案 A：Streamlit Community Cloud（免费）

### A1. 需要准备的条件

- GitHub 账号（用于承载代码仓库）
- 本机安装 Git，并配置好 GitHub 凭据
- 可选：安装 GitHub CLI（`gh`），可用命令一键建仓库并推送

### A2. 代码推送到 GitHub

在项目根目录执行：

```bash
cd d:/ai_study_web

# 1. 初始化仓库
git init
git add .
git commit -m "init: AI 大模型实战求职学习平台"

# 2. 方式一：使用 gh CLI 创建远程仓库并推送（推荐）
gh repo create ai-study-web --public --source . --push

# 方式二：没有 gh 时，先在 GitHub 网页新建空仓库，再：
git remote add origin https://github.com/<你的用户名>/ai-study-web.git
git push -u origin main
```

> 注意：提交前确认 `.gitignore` 已忽略 `__pycache__/`、`*.pyc`、`learning_tracker.db`、`_knowledge_cache.json` 等本地文件（模板见下方）。`课程原文及导读/` 与 `app.py`、`requirements.txt`、`core/`、`views/` 必须被包含。

### A3. 在 Streamlit Community Cloud 部署

1. 打开 <https://share.streamlit.io>，用 **GitHub 账号**登录（若未注册会引导授权 Streamlit 访问你的仓库）。
2. 点击 **New app**（或 **Create app**）：
   - **Repository**：选择 `ai-study-web`
   - **Branch**：`main`
   - **Main file path**：`app.py`
   - 点击 **Deploy**。
3. 等待构建完成（首次约 1~3 分钟，期间会安装 `requirements.txt` 依赖）。
4. 部署成功后获得公网地址，形如 `https://<你的应用名>.streamlit.app`。

### A4. 部署后必做（关键！）

代码会自动探测"本机局域网 IP"作为分享地址，部署到云端后必须手动改成公网地址，否则分享链接外部打不开：

1. 打开部署好的页面。
2. 左侧边栏「🔗 对外分享」→ 把「对外访问地址」改为 `https://<你的应用名>.streamlit.app`。
3. 重新生成分享链接，发给任何人即可访问（无需登录）。

### A5. 方案 A 注意事项

- **休眠冷启动**：免费层长时间无人访问会休眠，再次打开需等待十几秒。
- **数据可能重置**：重新部署 / 平台回收实例后，本地文件（错题本、已生成的分享链接）可能被清空 —— 这是免费层的限制。需要长期保留数据请用方案 B。
- **国内访问**：`.streamlit.app` 域名在国内偶发不稳定，主要访客在国内时建议方案 B。
- **API Key**：访客在页面自行填写，与部署无关，无需额外配置。

---

## 三、方案 B：国内云服务器（推荐长期使用）

### B1. 需要准备的条件

- 一台云服务器（推荐 2核2G，Ubuntu 22.04，可选国内 / 香港节点）
- 域名（可选）：用域名 + HTTPS 需要 ICP 备案（国内节点）；直接 `IP:端口` 访问不需要
- SSH 客户端（Windows 自带 `ssh` 或 MobaXterm / Xshell）

### B2. 步骤

1. **购买并初始化**：在云控制台创建轻量应用服务器，安装 Ubuntu 22.04 镜像。
2. **放行端口**：安全组 / 防火墙放行 TCP 8501（直接访问）或 80/443（配域名后）。
3. **上传代码**：`scp -r d:/ai_study_web root@<服务器IP>:/opt/`，或用宝塔面板上传。
4. **安装依赖并启动**：

   ```bash
   cd /opt/ai_study_web
   apt update && apt install -y python3 python3-venv
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   streamlit run app.py --server.address 0.0.0.0 --server.port 8501
   ```

5. **访问验证**：浏览器打开 `http://<服务器公网IP>:8501`。
6. **配成后台服务**（关掉 SSH 也不停）：写 systemd unit 文件，或 `nohup streamlit run app.py --server.address 0.0.0.0 --server.port 8501 &`。
7. **（可选）域名 + HTTPS**：Nginx 反代 8501 → 80/443，用 certbot 申请证书，最终地址 `https://<你的域名>/?share=<短码>`。
8. **改分享地址**：侧边栏「🔗 对外分享」→「对外访问地址」改为你的公网域名 / IP → 重新生成分享链接。

### B3. 方案 B 注意事项

- 数据（`learning_tracker.db`）完整保留在服务器磁盘，重启不丢。
- 用域名对外服务记得备案；裸 IP + 端口访问则无需。
- 建议给服务器配置好防火墙只放行必要端口。

---

## 四、方案 C：内网穿透（临时演示）

1. 本机保持应用运行：`streamlit run app.py`（8501）。
2. 安装并运行穿透工具，例如：
   - `ngrok http 8501`
   - `cpolar http 8501`
3. 获得一个公网地址，如 `https://xxxx.ngrok-free.app`。
4. 侧边栏「对外访问地址」填该地址 → 重新生成分享链接。

> 免费穿透地址通常有有效期、限速，仅适合临时展示。长期使用请用方案 A / B。

---

## 五、通用注意事项

1. **分享地址必须改**：`core/share.py` 的 `get_default_base_url()` 会自动探测本机地址。每次更换部署环境后，都要在侧边栏把「对外访问地址」改为新的公网地址，并**重新生成分享链接**。
2. **SQLite 持久化**：错题本、学习统计、分享链接记录都在 `learning_tracker.db`。免费 PaaS 文件系统是临时的，需要长期保留数据就用云服务器（方案 B）。
3. **知识库目录**：`课程原文及导读/` 缺失时课程列表不完整；上传后首次访问会自动解析并重建 `_knowledge_cache.json`。
4. **HTTPS**：PaaS 平台默认自带；云服务器裸 IP 访问建议配域名 + 证书。
5. **安全**：公开部署后任何拿到链接的人都能访问。「整个平台」级分享会把完整应用暴露给访客，对外尽量只发课程级分享链接。
6. **API Key**：当前设计为访客页面自行填写，云端无需配置。如后续希望服务器统一配置，可改为优先读取环境变量。

---

## 附：.gitignore 模板（推送到 GitHub 前使用）

```gitignore
__pycache__/
*.pyc
.vscode/
.idea/

# 本地数据与缓存（部署环境会自动重建，不提交）
learning_tracker.db
_knowledge_cache.json

# 如确需把错题本初始数据一起带过去，可注释掉 learning_tracker.db 这一行
```
