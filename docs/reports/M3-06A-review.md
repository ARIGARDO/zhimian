# M3-06A 阶段 A 整改与回归审核

## 兼容性事实

对比 `c2a23e5` 的 M3-05 基线：原 `create_from_preset()` 接受启用的 `bank` 或 `role` 预设及启用的无编号题目，满足题量和配置校验即可创建；JD 仅 `role` 可传。整改前 `ea282fe` 对无编号题目返回 409“题库尚无已审核版本”，即旧 `bank` 和旧 `role` 均无法新建；即便 `role` 题目有新审核材料，也因预设类型返回 409。已审核启用、材料合法的新版 `bank` 仍可创建；已有旧场次沿原快照和旧评价策略读取。正式库的当前内容本轮未查询，不以此前记录替代实时事实。

经产品批准，现已对纯旧无编号 `bank` 和 `role` 恢复 M3-05 创建路径，并在场次快照标记 `legacy-v1`，不提供新版审核材料、不标为已审核。新版 `bank` 保留审核及摘要约束，新旧题目混用被拒绝；审核版 `role` 暂不开放。旧 `role` 可继续提交 JD，旧场次不改写。

## 材料容量

`question_version.validate_review_capacity()` 对规范化、紧凑 Unicode JSON 序列化后的单题材料设置 1200 字符技术上限，超过时返回脱敏的明确冲突；创建新版面试时作为安全兜底检查。10 道主问题各携带一份材料最多约 12000 字符，给现有 24000 字符输入预算留下空间；题干、答案、JSON 结构和追问也要占预算，不能保证 10 题或长回答可生成报告。多追问会重复携带对应材料，可能提前超限；评价阶段仍按完整材料与完整回答检查并保留原始回答。

目前工程没有导入、审批或发布入口，不能声称数据库启用时已自动检查容量。未来发布工具应在审核和启用前调用此函数；当前仍可通过数据库直接启用超长材料，但创建面试会拒绝。字符数不等于 Token 或费用；不引入分批和新评分算法。

## 当前文件与测试

- `backend/app/services/question_version.py`：集中容量检查；`interview.py`：新建场次时检查；`interview_ai.py`：实际模型请求采用与预算检查一致的紧凑 JSON 序列化。
- `backend/tests/test_interview_reviewed.py`：Unicode 精确边界、超长材料拒绝及评价预算兜底；`test_interview_api.py`：旧 `bank`、`role`、新版 `bank` 恢复后的兼容行为；`integration_m306_compat.py`：真实 PostgreSQL 下 API 和容量回归。
- `cd backend && PYTHONPYCACHEPREFIX=/tmp/zhimian-pycache /tmp/zhimian-m306-py313/bin/pytest -q`：89 项通过，SQLite/ASGI 和模拟模型。误从仓库根目录运行一次时加载本地配置，已有模型 URL 测试失败；按上述目录重跑通过。
- 独立 PostgreSQL 容器、不挂载正式卷：`M306_TEST_DATABASE_URL=<隔离库> .../python tests/integration_m306_compat.py` 通过，旧 `bank` 和旧 `role` 可创建并沿旧路径开始、出题、回答和构建反馈上下文；新版审核 `bank` 可创建，混合题库、审核版 `role` 与超长材料返回 409，响应不泄漏材料。
- `cd frontend && npm run typecheck && npm run build && node --test tests/*.test.cjs`：类型检查、生产构建及 9 项前端测试通过。
- 未验证真实模型对长报告的输出完整性、评分质量、Token 用量及成本；自动化通过不等于模型质量验收。

## 迁移部署与恢复

本轮不新增或修改迁移。既有 `0008_reviewed_question_versions` 部署前应备份并恢复演练，在隔离环境验证 `0007 → 0008`、已有数据与锁影响，再按审批部署；部署后检查 `alembic current/heads` 和数据完整性。`0008` 禁止自动 downgrade；回退应用须先验证旧代码对新增结构及审核版本的兼容，保留历史版本和快照，优先前向修复；如确需恢复备份，应在明确停写、验证恢复点和批准后执行。不得覆盖已有学习、聊天或面试数据。

结论：获批的旧 `bank` 和旧 `role` 兼容路径已恢复；新版审核及材料容量保护保留，等待最终审核。未连接或修改正式数据库，未导入或启用正式题目，未开始 M3-06B。
