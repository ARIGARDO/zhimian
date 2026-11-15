"""M1 内置入门文章。后续由公共知识库内容管理替代。"""

TOPICS: list[dict[str, str | int]] = [
    {
        "id": "asyncio", "category": "python", "category_label": "Python 后端", "sort_order": 1,
        "title": "asyncio 与事件循环", "summary": "协程、事件循环与异步 I/O 的工作原理",
        "content_md": """# asyncio 与事件循环

> 本章要点：异步编程适合等待网络、数据库等 I/O 的场景，并不意味着单线程可以同时执行多个 CPU 密集任务。

## 为什么需要 asyncio？

同步程序在等待网络响应或数据库操作时，可能阻塞当前执行流程。`asyncio` 允许协程在 `await` 等待时交出控制权，由事件循环调度其他就绪任务。

这意味着**并发**不等同于**并行**：事件循环可以协调多个任务的等待与执行，但 CPU 密集工作依然可能阻塞事件循环。

## 事件循环与协程

使用 `async def` 定义协程函数，调用它得到协程对象。可以使用 `await` 等待协程，或者使用 `asyncio.create_task()` 将协程安排为任务。

```python
import asyncio

async def fetch_item(name: str) -> str:
    await asyncio.sleep(0.2)  # 模拟等待外部 I/O
    return f"已获取 {name}"

async def main():
    tasks = [asyncio.create_task(fetch_item(x)) for x in ["A", "B"]]
    print(await asyncio.gather(*tasks))

asyncio.run(main())
```

## 常见错误

- 在 `async def` 中直接调用阻塞式 `time.sleep()`。
- 认为给 CPU 密集任务加上 `async` 就会自动加速。
- 创建任务后没有等待或管理任务生命周期。

## 思考题

`asyncio.create_task()` 与直接 `await` 一个协程有什么区别？在 FastAPI 中调用同步、阻塞式数据库驱动会带来什么风险？
""",
    },
    {
        "id": "fastapi", "category": "python", "category_label": "Python 后端", "sort_order": 2,
        "title": "FastAPI 接口设计", "summary": "路由、参数校验、依赖注入与异步接口实践",
        "content_md": """# FastAPI 接口设计

> 本章要点：分清路由、数据验证与业务服务的职责。

## 路由与 Pydantic

FastAPI 用装饰器声明 HTTP 接口。Pydantic 模型可以描述请求和响应结构，并为 OpenAPI 文档提供类型信息。

```python
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI()

class CreateTask(BaseModel):
    title: str = Field(min_length=1)

@app.post("/tasks")
async def create_task(body: CreateTask):
    return {"title": body.title, "status": "pending"}
```

## 依赖注入

`Depends` 常用于提供数据库 Session、配置或可复用的校验逻辑。复杂业务规则应放在 Service 层，而不是全部写在路由函数中。

## 异步的边界

`async def` 适合等待异步 I/O；阻塞式文件解析或 CPU 密集计算需要合理隔离，不应长时间占据事件循环。

## 思考题

为什么前端 Zod 校验通过后，FastAPI 仍必须执行 Pydantic 校验？
""",
    },
    {
        "id": "redis", "category": "python", "category_label": "Python 后端", "sort_order": 3,
        "title": "Redis 缓存常见问题", "summary": "缓存穿透、击穿、雪崩与数据一致性",
        "content_md": """# Redis 缓存常见问题

## 缓存穿透

请求不断查询不存在的键，导致大量流量落到后端数据库。常见防护包括输入校验、缓存空值及布隆过滤器，但需要衡量误判与维护成本。

## 缓存击穿

热点键失效时大量请求同时查询数据库。可以考虑单飞机制、互斥锁、合理过期策略和热点预热。

## 缓存雪崩

大量缓存键在相近时间过期，造成集中回源压力。常见做法是给过期时间增加抖动、限流与降级。

```python
# 示意：为过期时间增加抖动，不代表完整缓存实现
import random
cache_ttl = 300 + random.randint(0, 60)
```

## 一致性

缓存与数据库的数据一致性通常需要在更新时明确删除/刷新策略，不能简单承诺绝对强一致。

## 思考题

哪些场景适合使用 Redis 作为缓存，哪些情况应该以 PostgreSQL 为权威数据源？
""",
    },
    {
        "id": "mysql", "category": "python", "category_label": "Python 后端", "sort_order": 4,
        "title": "MySQL 索引与查询优化", "summary": "B-Tree、联合索引与执行计划",
        "content_md": """# MySQL 索引与查询优化

## B-Tree 索引

MySQL InnoDB 常用 B+Tree 组织索引。索引有利于定位记录，但维护索引需要额外存储和写入成本。

## 联合索引

联合索引的字段顺序会影响可用的索引条件。需要结合实际过滤、排序和查询分布决定。

```sql
CREATE INDEX idx_orders_user_created ON orders (user_id, created_at);
EXPLAIN SELECT * FROM orders WHERE user_id = 42 ORDER BY created_at DESC;
```

## 执行计划

`EXPLAIN` 帮助判断访问方式、估计行数及索引使用情况；优化应基于真实查询计划，不应只靠口诀。

## 思考题

为什么索引越多不一定越好？复合索引和单列索引分别适合什么场景？
""",
    },
    {
        "id": "rag", "category": "ai", "category_label": "AI 应用 / Agent", "sort_order": 5,
        "title": "RAG 混合检索", "summary": "BM25、向量召回与结果融合",
        "content_md": """# RAG 混合检索

## 检索为什么需要两条路径？

关键词检索擅长精确术语和代码标识符，例如 `asyncio.create_task`；向量检索擅长自然语言表达的语义匹配。

两种检索路径可能返回不同排名，需要合并候选。

## 倒数排名融合（RRF）

RRF 按排名位置融合，而不是直接相加不同尺度的原始得分。

```python
def rrf(rank_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked in rank_lists:
        for rank, chunk_id in enumerate(ranked, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (k + rank)
    return scores
```

## 引用溯源

正确的引用必须来自真实检索结果，并能够映射到文章、章节或文件页码，不能让模型凭空编造引用。

## 思考题

为什么混合检索不一定总比纯向量检索更好？如何通过 Recall@K 和 nDCG@K 验证？
""",
    },
    {
        "id": "rerank", "category": "ai", "category_label": "AI 应用 / Agent", "sort_order": 6,
        "title": "RAG 重排序与评测", "summary": "Cross-Encoder、准确率与延迟权衡",
        "content_md": """# RAG 重排序与评测

## 召回与重排序

召回层优先找到可能相关的候选片段；重排序模型进一步估计问题与片段的相关性。重排序不能找回召回阶段已经漏掉的内容。

## 常用指标

- **Recall@K**：相关证据是否进入候选集合。
- **MRR**：第一个相关结果的排名。
- **nDCG@K**：整体列表的相关性质量。
- **证据支持率**：引用是否真正支持回答。

## 工程权衡

Cross-Encoder 等精排方法可能提升排序质量，但增加延迟和资源开销。需要与纯向量、关键词、RRF 混合检索建立相同测试集的对照。

## 思考题

为什么不能单凭大模型对自己的答案打分来判断整个 RAG 系统的好坏？
""",
    },
    {
        "id": "agent", "category": "ai", "category_label": "AI 应用 / Agent", "sort_order": 7,
        "title": "Agent 工具调用与安全", "summary": "工具编排、参数验证与权限控制",
        "content_md": """# Agent 工具调用与安全

## 工具调用的基本流程

模型可以提出调用某个工具的请求，但实际工具执行必须由应用端校验工具名称、参数、权限与资源限制。

## 为什么不能信任工具参数？

模型输出属于不可信输入；来自网页、文档和历史消息的内容也可能包含指令注入。执行数据库修改、外部网络访问等高风险操作时尤其需要限制。

```python
ALLOWED_TOOLS = {"search_knowledge", "get_topic"}

def check_tool(name: str) -> None:
    if name not in ALLOWED_TOOLS:
        raise ValueError("tool not allowed")
```

## 权限与确认

对于影响真实数据或需要付费的操作，设计明确的用户确认与审计机制。

## 思考题

为什么不能把模型生成的一段 JSON 直接转换成任意 Python 函数调用？
""",
    },
    {
        "id": "llm-eval", "category": "ai", "category_label": "AI 应用 / Agent", "sort_order": 8,
        "title": "LLM 应用评估", "summary": "测试集、幻觉、稳定性与成本",
        "content_md": """# LLM 应用评估

## 质量不仅是回答是否流畅

一个 AI 应用需要同时考虑回答正确性、证据忠实性、响应时间、成本和异常恢复能力。

## 建立可重复测试集

记录问题、预期答案要点、相关知识来源及异常场景；对比时保持相同模型配置和检索数据。

## 运行指标

- 请求成功率与超时比例。
- P50 / P95 延迟。
- Token 使用量与估计费用。
- 引用有效率和证据支持率。

## 思考题

为什么演示中的几条漂亮回答不能代替有覆盖面的回归测试？
""",
    },
]
