# 知面 · AI 智能学习与技术模拟面试平台

**架构基线：V2.5 · 当前交付：M2 智能问答（部分环境仍待验收）**

根据已确认 HTML V0.4 进行 React 组件化重建。当前实现范围：

- React 首页、方向/专题选择和专题阅读器（沿用 V0.4 风格）。
- FastAPI 提供真实专题列表、正文、阅读进度与概览 API。
- PostgreSQL 存储 8 个入门文章和单实例学习进度，使用 SQLAlchemy AsyncSession / Alembic。
- 阅读位置自动保存；**只有用户点击按钮才标记章节完成**。完成章节不等于知识掌握。
- AI 问答和专题独立会话、流式回复与历史记录；模型由服务端配置。
- 面试、知识库上传、任务及成长模块仍为后续里程碑。

## 1. 最简单的运行方式（需 Docker 与 Docker Compose）

```bash
cp .env.example .env
# 仅本机实验可使用示例密码；部署前请修改 .env

docker compose up --build -d
# 打开 http://127.0.0.1:8080
```

`init` 服务会自动执行 `alembic upgrade head` 和 `python -m app.seed`，可多次执行而不覆盖已有专题内容。PostgreSQL 使用持久化数据卷。

查看状态：

```bash
docker compose ps
docker compose logs -f backend
curl http://127.0.0.1:8080/api/v1/health
```

停止（保留数据）：`docker compose down`。**慎用 `docker compose down -v`，它会删除数据库卷。**

> Compose 默认只把 Web 服务绑定到 `127.0.0.1`。请不要直接修改为 `0.0.0.0` 对公网开放：当前无账号/权限隔离，公开前需先配置 HTTPS 和访问保护。详见 `docs/deployment/SECURITY.md`。

### 模型配置

在根目录 `.env`（Compose）或 `backend/.env`（单独启动后端）设置 `MODEL_BASE_URL`、`MODEL_NAME`、`MODEL_API_KEY`，可选设置 `MODEL_TIMEOUT`（秒）。地址应为兼容 OpenAI 的 API 基础路径，例如 `https://api.openai.com/v1`。修改后重启后端。密钥只保存在服务端环境，不提交仓库，也不放入前端。未配置时聊天会提示错误。

当前为单实例、单 worker 设计，部署到公网前须增加认证、HTTPS 和调用限额。专题正文会随该专题的提问发送给所配置的模型服务商；普通会话不会附带专题正文。

## 2. 分别启动前后端（学习开发模式）

启动数据库（Docker）：

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d postgres
```

后端（Python 3.11+，推荐 3.12）：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate       # Windows 使用 .venv\\Scripts\\activate
pip install -e '.[dev]'
cp .env.example .env
# 修改 .env 的 DATABASE_URL 连接到 localhost:5432
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

> `compose.dev.yaml` 仅为本地分离开发将 PostgreSQL 映射到 `127.0.0.1:5432`；不要在生产环境使用此覆盖文件向公网暴露数据库。最省事的初次体验仍是上面的 Docker 全栈运行。

前端：

```bash
cd frontend
npm install
npm run dev
# 浏览器访问 http://localhost:5173
```

Vite 将 `/api` 请求代理到 `http://localhost:8000`。前后端都独立启动时才可以进行联调。

## 3. API 与检查

- `GET /api/v1/health` — 应用健康检查
- `GET /api/v1/health/ready` — PostgreSQL 是否已就绪
- `GET /api/v1/topics` — 获取专题目录和进度
- `GET /api/v1/topics/{topic_id}` — 获取 Markdown 正文
- `GET /api/v1/progress/{topic_id}` — 获取阅读状态
- `PATCH /api/v1/progress/{topic_id}` — 保存阅读位置或手动完成状态
- `GET /api/v1/overview` — 当前学习进度概览
- `GET/POST /api/v1/conversations`、`PATCH/DELETE /api/v1/conversations/{id}` — 会话管理（列表按专题或普通问答过滤）
- `GET /api/v1/conversations/{id}/messages`、`POST /api/v1/conversations/{id}/messages/stream` — 消息历史和 SSE 流式回复；专题会话的读取、发送、修改和删除需携带 `?topic_id=<专题ID>`。
- `/docs` — FastAPI Swagger UI；`/openapi.json` — Hey API 未来生成类型的契约来源

阅读进度请求例子：

```bash
curl -X PATCH http://127.0.0.1:8080/api/v1/progress/asyncio \
  -H 'Content-Type: application/json' \
  -d '{"reading_position":0.35}'

# 仅由用户手动操作对应的接口才变更完成标记
curl -X PATCH http://127.0.0.1:8080/api/v1/progress/asyncio \
  -H 'Content-Type: application/json' \
  -d '{"completed":true}'
```

测试：

```bash
cd backend
pytest -q
python -m compileall -q app
cd ../frontend
npm run build
```

## 4. 目录与里程碑

- `frontend/` — React + TypeScript + Vite、路由、学习 UI
- `backend/` — FastAPI、SQLAlchemy 2.x、Alembic、内置内容
- `infra/nginx/` — 生产静态资源与 `/api` 反向代理
- `compose.yaml` — 前后端 + PostgreSQL + 初始化服务
- `docs/architecture/DECISIONS.md` — 架构 V2.5 的开发范围与不可更改的产品规则

M2：独立 AI 问答与专题聊天、OpenAI 兼容接口、SSE 流式输出（真实模型联调待验收）。
M3：模拟面试、追问、完整和部分复盘。
M4：公共/外部知识库、文件解析、Embedding、pgvector、混合检索、Redis/Celery。
M5：任务、掌握证据、成长面板、测试与开源交付。

## 5. 验证范围与限制

后端测试使用 SQLite 和模拟模型服务验证基础会话流程，不等同于真实 PostgreSQL、浏览器取消及真实模型服务的端到端验收。请在 Docker 可用的环境执行迁移和联调。

- PostgreSQL 会话锁用于防止同一会话并发生成；异常退出后的残留状态在下次读取或发送时恢复。
- 历史消息采用字符预算而非精确 token 预算，长会话仍可能超出部分模型限制。
- 当前不提供用户隔离或公开部署所需的访问控制。

## 独立演示环境

```bash
docker compose -f compose.demo.yaml up -d --build
```

访问 <http://127.0.0.1:8081/>。该环境使用独立的 `zhimian-demo` 数据库卷、明确标记的示例题库和本地模拟模型；输出仅用于验证交互，不能作为真实模型评价。岗位演示可填写 JD，但示例题是固定题目，不会依据 JD 动态出题。它不读取项目 `.env` 中的模型密钥，不连接现有知面数据库。正常运行仍使用 `docker compose up -d --build` 和端口 8080，正常环境按自身配置连接模型；正式题库须另行审核启用。

停止演示：`docker compose -f compose.demo.yaml stop`。演示数据保留在独立卷中；删除卷会永久删除演示记录。首次构建需下载依赖。

面试复盘中的单题评价可由用户选择专题并确认加入学习任务；任务与专题完成状态互不联动。问答融合内置专题关键词与可选 pgvector 章节向量检索，并展示实际送入模型的资料；来源列表不保证模型每个结论都有依据。演示环境使用本地模拟向量，不能作为语义检索质量验证。学习专题建议仅按复盘文字做关键词匹配，非独立 AI 推荐；真实模型质量验证仍未完成。

### 可选的向量索引

默认未配置 Embedding，问答会自动回退关键词检索。要使用真实供应商，需在本地 `.env` 配置 `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL` 和 `EMBEDDING_API_KEY`，该接口必须兼容 OpenAI `/embeddings` 并支持 384 维输出。配置完成并自行确认费用后，运行 `docker compose run --rm backend python -m app.tools.index_knowledge` 创建或增量更新索引；该命令会调用供应商并可能产生费用。文章变化后需重新索引，旧索引不会作为当前章节结果返回。

岗位 JD 使用有限技术词表确定性匹配，优先排列命中题目；未识别、未命中或题量不足会显示回退/错误提示。岗位预设可用 `bank_preset_id` 引用已启用审核题库；演示环境中的审核标记仅用于隔离测试。
