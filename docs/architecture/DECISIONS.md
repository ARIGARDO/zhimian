# 技术架构基线 V2.5（M1 范围）

## 已确认架构

- 前端：React + TypeScript + Vite；React Router 声明式模式；TanStack Query；按需 Zustand；shadcn/ui + Tailwind CSS；复杂表单采用 React Hook Form + Zod。
- API：Python FastAPI + Pydantic；SQLAlchemy 2.x AsyncSession + Alembic。
- 数据：PostgreSQL + pgvector。
- 模型：OpenAI 兼容接口优先，自定义 Chat/Embedding 适配层；MVP Embedding 使用云端 API，保留本地扩展。
- RAG：原生 Python，关键词 + 向量召回 + RRF；Markdown/TXT/文本型 PDF/DOCX。
- 任务：Redis + Celery + 独立 Worker。
- API 类型：Hey API 生成 TypeScript Fetch SDK，自主封装业务 TanStack Query Hooks。
- 部署方向：Docker Compose + Nginx，个人/可信环境自部署；不实现平台注册登录。
- 原则：成熟稳定、少依赖、模块化单体、根据里程碑逐步实现。

## M1 已实施

- React 外壳、首页、学习目录、专题阅读器、手动标记完成；M2+ 模块为明确的占位页面。
- FastAPI 学习专题/阅读进度/概览 API 与 Pydantic 校验。
- PostgreSQL ORM + AsyncSession + Alembic 迁移 + 8 个内置专题种子。
- Docker Compose 开发版包含 frontend/backend/init/postgres（Redis/Celery 尚未接入）。
- 基础 pytest 测试。

## 实施时必须保留的产品规则

1. 阅读到底或点击文章不等于“完成”，完成只能由用户手动确认。
2. 文章完成不等于知识掌握；后续掌握度基于其他有效证据。
3. 智能学习先选方向与专题，阅读页侧栏仅显示当前方向；专题 AI 会话后续独立存储。
4. AI 问答直接打开空白输入页；首次提问后才创建会话。
5. 已完成面试与未完成面试分离；未完成只允许有效回答的部分复盘，不产生综合评分与默认任务。
6. 推荐任务必须用户确认后才加入正式任务。
7. 公共与外部知识库上下排列，均支持新增，并检查重复/主题重合。
8. 无平台注册登录不代表无访问控制：M1 仅本机绑定，公网部署必须补访问保护。

## 待实现、不可误称已完成

- Chat、LLM API 配置、专题 AI（M2）；模拟面试与复盘（M3）；文档上传、Embedding、pgvector 向量索引、Redis/Celery、混合检索（M4）；成长与任务（M5）。
- Hey API、RHF/Zod、完整 shadcn 组件、Playwright 等随功能增加时接入，避免 M1 空依赖。
