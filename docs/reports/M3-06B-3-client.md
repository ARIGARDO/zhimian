# M3-06B-3 模型客户端隔离验收准备

本次仅改造客户端并使用模拟 HTTP；未调用真实模型、导入题库或连接数据库。默认配置不增加请求字段，不改变生产配置。`MODEL_ENABLE_THINKING` 不设置时不发送；设置为 `false` 时发送顶层 `enable_thinking: false`。

## 隔离环境配置示例

以下仅为后续获授权后使用的示例，不包含密钥；不要放进正式配置文件：

```dotenv
MODEL_BASE_URL=https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1
MODEL_NAME=qwen3.8-flash
MODEL_ENABLE_THINKING=false
MODEL_TEST_INCLUDE_USAGE=true
MODEL_TEST_LEDGER_PATH=/隔离目录/model-acceptance-ledger.json
MODEL_AI_MAX_ATTEMPTS=1
MODEL_AI_MAX_OUTPUT_TOKENS=1024
```

使用前须在隔离目录中由运行账号预置一个权限为 `0600` 的普通文件，内容为 `{"version":1,"limit":8,"requests":[]}`；文件路径必须为绝对路径。账本不得存放或挂载在仓库、公开目录或正式环境中。验收期间不得重置、替换或复制账本；所有会使用测试账户的进程必须使用同一文件和同一账号，确保跨容器时文件锁和 inode 共享。文件需要持久保存至核对结束；账本丢失或损坏时停止测试，不得新建空账本继续。

账本通过文件锁在每次发出 HTTP 请求前持久记录额度，失败、超时和进程崩溃都占用一次，最多认领 8 次；并发进程共享同一账本时生效。该机制不约束绕过账本、使用其他路径或无共享锁的进程，也不是多机分布式限额或供应商计费硬上限。必须隔离测试凭据并禁止其他客户端使用。账本不可用时拒绝请求；运行中进程崩溃可留下 `started`，其用量未知且额度不退还。

仅显式启用 `MODEL_TEST_INCLUDE_USAGE` 时发送 `stream_options.include_usage`，且必须配置账本。账本记录时间、操作 ID（面试模型调用时）、响应 ID、HTTP 请求 ID、返回模型名、实际返回的输入/输出/总 Token 和成功或失败；没有收到时相应字段为 `null`（未知）。不写入密钥、完整输入、内部材料或输出。`length` 后在流正常结束或断流前尝试接收用量，但仍返回失败，不能将截断报告保存为成功；如果等待超时或被取消，最终用量可能未知。账本无法记录完成状态时调用失败。

本工具不保存供应商账单或完整原始输出。后续测试应另行使用获批准的受控证据位置保存合成输入、原始输出并核对供应商账单，不应写入普通日志；需事先确认供应商账户的可执行费用硬上限。配置计数和 Token 上限不能等同于金额硬上限。

## 测试及限制

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/zhimian-pycache /tmp/zhimian-m306-py313/bin/pytest -q -p no:cacheprovider tests/test_model_acceptance.py`：8 项通过，覆盖默认请求、关闭思考、空 choices 用量、截断、断流、无效 JSON、缺失用量、失败计数和多进程竞争。
- 不涉及数据库的既有客户端、部分报告过滤及报告引用校验回归，与新测试合计 35 项通过；执行命令见提交结果。
- 全部后端测试及依赖 SQLite 的聊天、追问、反馈和报告集成回归需要数据库写入；由于本轮明确禁止任何数据库写操作，未执行这些测试，不将其视为通过。可在获准使用隔离临时数据库后补跑。
- 未验证真实 Qwen 地址、服务端 SSE、模型质量和账单，未执行真实模型调用。正式费用硬上限、题库隔离导入与四场真实验收均等待单独授权。
