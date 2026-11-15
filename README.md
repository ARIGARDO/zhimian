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
- `GET /api/v1/conversations/{id}/messages`、`POST /api/v1/conversations/{id}/messages/stream` — 消息历史和 SSE 流式回复
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

- 会话并发限制仅在单进程内有效；进程异常退出时可能留下 `streaming` 状态。
- 历史消息目前未做上下文长度裁剪；长会话可能超出模型限制。
- 当前不提供用户隔离或公开部署所需的访问控制。
