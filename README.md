# 知面 · AI 学习与模拟面试

知面是面向本地自部署的学习和面试练习项目。MVP 候选版支持专题阅读与进度、知识问答和历史会话、文字模拟面试与追问、完整报告或部分复盘，以及由用户确认的学习任务。任务完成不会自动标记知识掌握。

技术栈：React、TypeScript、Vite、FastAPI、PostgreSQL、pgvector、Alembic，以及 OpenAI 兼容模型接口。单实例 BYOK，不提供注册或多用户隔离。

## 快速体验：隔离演示

需要 Docker Desktop / Docker Engine 和 Docker Compose v2，首次构建需要下载镜像及依赖。

```bash
git clone https://github.com/ARIGARDO/zhimian.git
cd zhimian
docker compose -f compose.demo.yaml up -d --build
```

打开 <http://127.0.0.1:8081/>。演示使用独立数据库卷、测试专用题库标记、本地模拟模型和模拟向量；页面有演示标识。模拟输出和分数不代表真实模型能力，测试审核标记不代表正式审核。岗位 JD 会对现有题目排序，不会生成新题。

```bash
docker compose -f compose.demo.yaml ps
docker compose -f compose.demo.yaml logs --tail=100 backend
docker compose -f compose.demo.yaml stop  # 保留演示数据
```

## 本地自部署与 BYOK

```bash
cp .env.example .env
# 按需编辑 .env，填写自己的聊天模型配置；不要提交该文件。
docker compose up -d --build
# 打开 http://127.0.0.1:8080/
```

首次启动自动执行 Alembic 迁移并插入 8 个公共专题，不覆盖已有专题。PostgreSQL 使用独立数据卷。普通模式默认没有正式题库；知识学习可直接使用，面试需先按下文审核并启用题目。

```bash
docker compose ps
docker compose logs --tail=100 backend
docker compose stop             # 停止并保留数据
docker compose up -d            # 重新启动
docker compose down             # 删除容器和网络，保留数据卷
```

`docker compose down -v` 会删除数据库卷，请勿用于需要保留的数据。数据库仅供 Compose 内部访问；Web 绑定 `127.0.0.1`。当前没有用户认证和权限隔离，**不要直接对公网开放**。变更或升级现有数据库前先备份数据卷，并确认当前迁移状态。

聊天模型只在服务端通过 `.env` 的 `MODEL_BASE_URL`、`MODEL_NAME`、`MODEL_API_KEY` 配置；地址应指向 OpenAI 兼容 API 的基础路径。未配置时聊天会显示配置错误。使用真实供应商可能产生费用，并会向其发送用户提问、相关会话及检索到的知识片段；请先确认服务商条款和费用。密钥不要放到前端、日志或 Git 中。

打开应用的“系统配置”可查看配置字段是否完整和地址格式是否有效；该页面不接收密钥，也不会请求供应商，因此不能证明密钥有效或服务兼容。修改 `.env` 后运行 `docker compose up -d --force-recreate backend` 重新创建服务，单纯 `restart` 不会更新容器环境变量。

## 题库审核与启用

[候选题清单](docs/interview/M3-06A-question-manifest.json)和[逐题签核表](docs/interview/M3-06A-signoff.md)可供人工核对；当前清单的状态是待审核。正式审核由负责人逐题决定，演示库中的测试标记不能作为正式审核。工具不会自动批准题目。

使用后端环境查看每道题的内容摘要，供审核人核对：

```bash
# 以下命令从仓库根目录运行；/materials 是只读挂载。
docker compose run --rm -v "$PWD/docs/interview:/materials:ro" backend \
  python -m app.tools.publish_interview_bank --manifest /materials/M3-06A-question-manifest.json
```

负责人在仓库外准备 UTF-8 JSON 签核文件，例如 `~/.config/zhimian/question-approval.json`。`questions` 只填写实际批准的题目编号及上一步输出的完整 SHA-256 摘要；以下空值只是格式示意，不能通过校验：

```json
{"reviewer":"", "approved_at":"", "questions":{"P01":""}}
```

填写实际审核人、带时区的 ISO 8601 审核时间及逐题摘要后，可先只校验，再分别执行审核入库和启用：

```bash
# 仅将签核文件只读挂载；请先自行确认文件内容和目标数据库。
docker compose run --rm -v "$PWD/docs/interview:/materials:ro" -v "$HOME/.config/zhimian/question-approval.json:/approval.json:ro" backend \
  python -m app.tools.publish_interview_bank --manifest /materials/M3-06A-question-manifest.json --approval /approval.json
# 审核入库，不启用
docker compose run --rm -v "$PWD/docs/interview:/materials:ro" -v "$HOME/.config/zhimian/question-approval.json:/approval.json:ro" backend \
  python -m app.tools.publish_interview_bank --manifest /materials/M3-06A-question-manifest.json --approval /approval.json --apply
# 单独启用已经审核入库的题目
docker compose run --rm -v "$PWD/docs/interview:/materials:ro" -v "$HOME/.config/zhimian/question-approval.json:/approval.json:ro" backend \
  python -m app.tools.publish_interview_bank --manifest /materials/M3-06A-question-manifest.json --approval /approval.json --enable
```

签核文件是本地操作人的声明，并非加密身份签名；请妥善保存实际审批证据。工具核验题目完整摘要、保留审核人和时间，重复执行不重复创建；已发布内容不可覆盖，变更须创建新版本。未审核题目不会被混入；题量不足会提示。数据库约束需正常保留，历史场次继续使用冻结版本。

## Embedding 与知识引用

Embedding 默认使用本地 CPU 的 `intfloat/multilingual-e5-small`（384 维），不需要云端 Embedding 密钥。首次运行 `docker compose run --rm backend python -m app.tools.index_knowledge` 会下载模型并建立索引；模型缓存存放于 Docker 卷 `embedding-cache`。切换模型后再次执行该命令，新模型使用独立身份，不混用旧向量。模型未下载、加载或推理失败时自动回退关键词检索。可选 `EMBEDDING_PROVIDER=openai` 和独立的 `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_API_KEY` 使用兼容接口，可能产生费用。RRF 来源链接对应检索到的章节，不保证回答每项结论均被来源支持。

配置真实供应商并确认费用后，显式构建索引：

```bash
docker compose run --rm backend python -m app.tools.index_knowledge
```

本地模式首次执行会下载模型，远程模式则可能产生供应商费用。文章更新或切换供应商、模型后需重新索引；未重建期间回退关键词检索。同一模型名称下的权重更新需添加 `--force`，并在逐条重建期间暂停问答，避免混用不同版本的向量。演示模式只调用容器内模拟服务；模拟向量不能验证真实语义检索质量。

## 测试与已知限制

```bash
cd backend
python -m pip install -e '.[dev]'
pytest -q
python -m compileall -q app alembic
cd ../frontend
npm install
npm run typecheck
node --test tests/*.test.cjs
npm run build
```

- JD 使用有限关键词匹配与排序，非语义解析或动态出题；无匹配时退回预设题库。
- 真实模型质量、评分一致性和真实 Embedding 效果尚未完成全面验收；完整报告分数仍是候选量表。
- 文章检索基于当前内置专题，未提供个人文件上传；任务建议为关键词匹配，需用户确认。
- 阅读和聊天历史使用单实例数据；长上下文预算按字符估算，非精确 Token 或费用上限。
- `docs/architecture/DECISIONS.md` 和 `docs/reports/` 保存架构决策及历史验收记录。
