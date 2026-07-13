# Qdrant Local RAG 功能需求

## 1. 文档状态

- 状态：已实现；本文作为批准需求基线保留用于追溯
- 阶段：存储架构演进第一阶段
- 目标：为 DataPilot 增加按数据源隔离的本地 RAG 知识检索能力

以下要求保留批准时的完整约束，不因实现完成而弱化；当前运行方式见 `README.md`，实现架构见 `docs/mvp-design.md`。

本文档可作为后续 AI 开发任务的需求输入。实施前必须先完整分析现有代码并给出最小实现方案，得到人工确认后才能修改代码。

## 2. 实现目标

在 Agent 生成 SQL 之前，从知识库召回与当前问题相关的：

- 表和字段业务说明
- 指标定义
- 可信 SQL
- 点赞且执行成功的历史问答

将召回内容注入现有 SQL 生成上下文，提高中文 Text-to-SQL 的准确率和业务语义理解能力。

目标工作流：

```text
retrieve_schema
→ retrieve_knowledge
→ generate_sql
→ validate_sql
→ execute_sql
→ analyze_result
```

RAG 只增强 SQL 生成上下文。生成的 SQL 仍必须经过现有 SQLGlot、表白名单、字段白名单、只读、LIMIT 和超时校验。

## 3. 技术选型

### 3.1 向量数据库

使用 Qdrant Local Mode：

- 使用官方 `qdrant-client`。
- 本阶段不部署独立 Qdrant Server。
- 不在 `docker-compose.yml` 中新增 Qdrant 服务。
- 数据持久化到 `data/qdrant/`。
- Qdrant 数据目录不得提交到 Git。
- 后续可迁移到 Qdrant Server 或 Qdrant Cloud，但本阶段不新增通用向量数据库抽象层。

### 3.2 Embedding 模型

固定使用：

```text
BAAI/bge-small-zh-v1.5
```

要求：

- 使用 `sentence-transformers` 本地加载。
- 不调用任何外部 Embedding API。
- 向量维度固定为 512。
- Qdrant 使用 Cosine 相似度。
- 模型首次运行允许从 Hugging Face 下载，之后使用本地缓存。
- 本阶段不实现多模型切换、Reranker、`bge-m3` 或 Qwen3 Embedding。
- 后续出现真实中英文检索需求时，再使用新 Collection 重建全部索引。

建议 Collection 名称：

```text
datapilot_knowledge_bge_small_zh_v15
```

不同 Embedding 模型生成的向量不得写入同一个 Collection。

## 4. 知识范围

### 4.1 Schema 知识

索引当前数据源中的：

- 表名和表业务说明
- 字段名、字段类型和字段业务说明
- 表和字段是否属于查询白名单

优先复用现有 Schema、数据目录和语义描述逻辑。英文标识符与中文说明组合为同一条知识，例如：

```text
表：orders
业务说明：订单表

字段：created_at
业务说明：订单创建时间
```

### 4.2 指标定义

索引现有指标定义，包括：

- 指标名称和说明
- 计算公式
- 关联表和字段
- 过滤条件
- 所属数据源

必须复用现有语义层和指标存储。

### 4.3 可信 SQL

索引现有可信 SQL，包括：

- 用户问题
- SQL 和 SQL 解释
- 使用的表和字段
- 所属数据源

召回的可信 SQL 只能作为参考，必须重新通过完整 SQL 安全校验后才能执行。

### 4.4 高质量历史问答

只索引同时满足以下条件的记录：

- SQL 执行成功
- 用户明确点赞
- 存在有效问题和答案
- 能够确定 `data_source_id`
- SQL 通过所属数据源的表和字段白名单校验

建议索引用户问题、SQL、SQL 解释和中文总结，不保存完整原始查询结果。

## 5. 数据源隔离

每条 Qdrant Point 至少包含：

```text
data_source_id
knowledge_type
source_id
title
content
queryable
```

`knowledge_type` 至少支持：

```text
schema
metric
trusted_sql
historical_qa
```

每次检索必须使用 Qdrant Payload Filter 强制限定：

```text
data_source_id == 当前会话选择的数据源
queryable == true
```

禁止只依赖 Prompt 隔离数据源或可查询状态。没有明确 `data_source_id` 的知识不得进入索引，`queryable=false` 的知识不得召回，必须防止不同数据库或不同企业之间发生 Schema、指标和 SQL 串用。

## 6. 索引构建

新增最小可用的重建脚本：

```text
scripts/rebuild_knowledge_index.py
```

运行方式：

```bash
python scripts/rebuild_knowledge_index.py
```

要求：

- 从现有数据库和业务定义中读取知识。
- 创建或重建 Qdrant Collection。
- 使用 `bge-small-zh-v1.5` 生成向量。
- 写入必要的 Payload。
- 输出每种知识类型的写入数量。
- 使用稳定 ID 或重建 Collection 保证幂等，重复执行不产生重复向量。
- 不把数据库密码、连接地址或原始敏感数据写入 Qdrant。
- 错误信息不得泄露数据库密码。

本阶段不新增后台定时任务、Celery 或消息队列。

## 7. LangGraph 工作流

新增 `retrieve_knowledge` 节点，职责为：

1. 获取当前问题和 `data_source_id`。
2. 使用本地 Embedding 模型生成查询向量。
3. 按 `data_source_id` 过滤并召回相关知识。
4. 将召回内容整理为长度受限的参考上下文。
5. 写入现有 Agent State。
6. 供 `generate_sql` 节点使用。

要求：

- 复用现有 State 和节点组织方式。
- 不重构整个 LangGraph 工作流。
- 不改为 ReAct Agent，不新增多智能体。
- 检索节点不得执行 SQL。
- 召回内容必须明确标记为参考知识，不能覆盖系统安全规则。

## 8. 降级机制

以下情况必须自动回退原有查询流程：

- Qdrant 数据目录或 Collection 不存在
- Qdrant 查询失败
- Embedding 模型加载失败
- 当前数据源没有知识
- 检索结果为空

降级后继续执行 Schema 获取、SQL 生成、安全校验和查询。不得因为 RAG 故障导致 `/api/chat` 不可用，也不得向客户端暴露内部异常和本地路径。

## 9. API 返回

现有 `POST /api/chat` 增加兼容性可选字段：

```json
{
  "knowledge_sources": [
    {
      "knowledge_type": "metric",
      "source_id": "12",
      "title": "销售额",
      "score": 0.87
    }
  ]
}
```

要求：

- 没有召回时返回空数组。
- 不删除或修改现有返回字段。
- 不返回完整向量和不必要的完整知识正文。
- 不返回数据库连接地址、密码或其他敏感配置。

## 10. 配置

按照项目现有配置风格增加最少配置：

```env
QDRANT_PATH=data/qdrant
QDRANT_COLLECTION=datapilot_knowledge_bge_small_zh_v15
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
KNOWLEDGE_TOP_K=5
```

更新 `.env.example`，但不得提交真实 `.env`。本阶段不实现运行时模型切换或复杂配置中心。

## 11. 安全要求

- 所有生成 SQL 必须经过 `app/services/sql_validator.py`。
- 只允许一条 `SELECT`。
- 禁止 INSERT、UPDATE、DELETE、DDL、注释、多语句和 `SELECT *`。
- 只能访问当前数据源白名单中的表和字段。
- 自动增加或收敛为 `LIMIT 100`。
- 召回的 SQL 不得直接执行。
- 检索内容不得修改系统安全规则。
- Qdrant Payload、日志和 API 不得出现数据库密码或完整连接 URL。
- 不允许大模型调用任意 Python 代码或系统命令。

## 12. 测试要求

自动化测试必须：

- 不访问真实 DeepSeek。
- 不访问 Hugging Face 网络。
- 不下载真实 Embedding 模型。
- 不依赖真实 Qdrant Server。
- 使用 Fake Embedder 或 Fake Retriever 保持确定性。

至少覆盖：

1. 知识可以转换为向量并写入本地知识库。
2. 重复构建索引不会产生重复知识。
3. 不同 `data_source_id` 的知识不会互相召回。
4. `queryable=false` 的知识不会被召回。
5. Schema、指标、可信 SQL 和高质量历史问答能够正确进入索引和召回。
6. 未点赞或执行失败的问答不会进入索引。
7. 可信 SQL 仍必须经过 SQL 安全校验。
8. Qdrant 不可用或无召回时 `/api/chat` 回退原流程。
9. `/api/chat` 返回 `knowledge_sources`。
10. 危险 SQL 不会因为来自知识库而执行。
11. 数据库密码和连接地址不会进入 Payload、日志或 API。
12. SQLite、PostgreSQL、MySQL 和数据源管理原有功能不受影响。

最终验证：

```bash
python -m pytest -q
python scripts/run_evals.py
git diff --check
```

## 13. 文档要求

实现完成后，根据实际代码更新：

- `README.md`
- `docs/mvp-design.md`
- `docs/storage-architecture-roadmap.md`

需要说明依赖安装、首次模型下载、索引重建、Qdrant 数据位置、Collection 清理、RAG 使用方式、Local Mode 限制和未来服务化迁移方式。

## 14. 明确不做

本阶段不增加：

- Qdrant Server 或 Qdrant Cloud
- Redis、Celery、Kafka
- 多智能体或 ReAct 循环
- Reranker、Hybrid Search
- 文件上传和文档解析
- 知识库管理后台
- 多 Embedding 模型切换框架
- 与本需求无关的数据库重构或前端代码

## 15. 最小改动原则

- 先查找并复用现有组件、工具函数、接口和项目风格。
- 不新增通用向量数据库抽象层、Provider 工厂或未来占位接口。
- 不重构现有数据库层。
- 不修改无关代码。
- 修改尽量少的文件。
- 只实现最小可用的本地 RAG 闭环。
- 新增依赖前先确认现有依赖无法满足需求。

## 16. 验收标准

1. 索引脚本可以生成并持久化本地 Qdrant 知识库。
2. Agent 可以召回当前问题相关的知识。
3. 检索严格按照 `data_source_id` 隔离，并过滤 `queryable=false` 的知识。
4. 召回结果能够注入 SQL 生成上下文。
5. `/api/chat` 返回知识来源。
6. Qdrant 不可用时原有查询功能仍然正常。
7. 所有 SQL 仍经过完整安全校验。
8. 不泄露数据库密码、连接地址和敏感数据。
9. 全量 pytest 和 eval 通过。

## 17. AI 实施约束

AI 接收本文档后，第一阶段只允许：

1. 阅读本文档及相关设计文档。
2. 完整分析后端现有代码和实际调用链。
3. 列出可以复用的现有组件。
4. 给出最小实施方案、预计文件范围、测试方案、风险和合理假设。
5. 将非必要扩展建议单独列出。

如果存在阻塞问题，最多询问 3 个关键问题。没有阻塞时直接采用合理假设。

在获得人工明确确认前，AI 不得修改代码、安装依赖、创建实现文件或提交 Git。
