# M1 开发 Agent 任务分发与验收

## 已完成的初始交付

1. React + TypeScript + Vite 工程骨架与全局布局；首页、学习目录、专题文章页面。
2. FastAPI 学习业务路由、Pydantic Schema、SQLAlchemy AsyncSession 模型与 Service。
3. Alembic 初始迁移、8 篇教程种子与 Docker Compose 基线。
4. 健康检查、OpenAPI、进度字段校验、文章种子基础测试。

## 下一位开发 Agent 优先执行（请先阅读现有代码）

1. 在有网络与 Docker 的环境执行 `docker compose up --build -d`。如有依赖版本冲突，尽量以已确认成熟主版本作兼容修订，不更换技术栈。
2. 使用 `npm install` 生成并提交 `package-lock.json`；将构建/CI 改为 `npm ci`，跑 `npm run build` 和类型检查。
3. 使用真实 PostgreSQL 运行 Alembic 迁移与种子，验证 Topic 列表、阅读进度 upsert、完成状态与页面刷新。
4. 在桌面和移动端对照 `docs/reference/prototype-v0.4.html`，修复布局和交互差异。
5. 加入基于临时测试数据库的 API 集成测试，确保读到底不会自动设为 completed。
6. 完善阅读位置异步保存的并发顺序保障：避免过期的 scroll PATCH 覆盖最新位置；离开页面时应尽力保存但不能声称保证成功。
7. 评估原型和 shadcn/ui 基础组件一致性，后续按业务需要安装更多组件。

## 不允许的偏离

- 未经批准不增加注册登录系统，也不要将无账号单实例直接做成匿名公网服务。
- 不得将虚构的 AI、面试或知识库响应描述为已实现。
- 文章浏览与滚动不得自动标记已完成，完成按钮必须人工触发。
- M1 不必先安装 Celery/Redis，不得引入微服务与额外状态框架。
- API Key 不得放入 React 前端、VITE_ 环境变量或 GitHub 提交内容。

## 本次验证状态

- Python pytest：通过（见 README）。
- Python compileall：通过。
- Alembic 离线 SQL 生成：通过。
- TS/TSX 语法解析：通过（不等于完整类型检查）。
- npm 包安装、完整 TS 类型检查、Vite 构建、Docker Compose 和真实数据库集成：当前环境未验证。
