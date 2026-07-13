# DataPilot 存储架构演进路线

## 1. 目标

DataPilot 当前同时涉及 SQLite、PostgreSQL 和 MySQL。后续还计划接入 Qdrant 与 Redis，如果全部作为默认运行依赖，会增加部署、调试和维护成本，也容易让个人项目变成技术栈堆叠。

长期目标是把默认存储收敛为三个职责互不重叠的组件：

```text
MySQL   = 关系型数据和持久化事实来源
Qdrant  = RAG 向量知识库
Redis   = 可丢失、可重建的缓存
```

## 2. 目标架构

```text
FastAPI + LangGraph
├── MySQL 元数据库（读写账号）
│   ├── data_sources
│   ├── metrics
│   ├── query_logs
│   ├── chat_sessions
│   └── chat_messages
│
├── 企业 MySQL 业务库（只读账号）
│   └── 订单、用户、商品及其他业务表
│
├── Qdrant
│   ├── 字段和表的业务说明
│   ├── 指标口径与业务术语
│   ├── 历史可信 SQL
│   └── 用户认可的问答样例
│
└── Redis（按实际性能需求启用）
    ├── Schema 缓存
    ├── 热门查询结果缓存
    ├── 短期会话缓存
    └── 接口限流
```

## 3. 组件职责

### MySQL

MySQL 是唯一需要保证持久性和事务一致性的存储。

- `datapilot_meta` 保存数据源配置、指标、日志、会话和反馈。
- 企业业务数据库由 Agent 通过独立只读账号访问。
- 元数据库账号与业务数据库账号必须分离：前者可读写平台数据，后者只能 `SELECT` 业务表。
- 数据库连接密码不得写入日志或 API 响应，后续应迁移到环境变量或 Secret Manager。

### Qdrant

Qdrant 只保存 RAG 检索需要的文本、向量和过滤元数据，不承担事务配置与日志统计。

阶段一使用官方 `qdrant-client` Local Mode，数据保存在 `data/qdrant/`。Embedding 模型固定为 `BAAI/bge-small-zh-v1.5`，向量为 512 维、Cosine 距离；每个模型使用独立 Collection，不能混写向量。

每条知识至少包含：

```json
{
  "data_source_id": 7,
  "knowledge_type": "metric",
  "source_id": "12",
  "title": "销售额",
  "content": "指标定义和允许字段",
  "queryable": true
}
```

检索必须使用 Qdrant Payload Filter 同时限定 `data_source_id` 和 `queryable=true`，避免不同数据库、企业或非白名单元数据之间发生知识串用。召回内容只用于增强 Prompt，生成的 SQL 仍必须通过现有 SQLGlot、表白名单、字段白名单、`LIMIT` 和查询超时保护。

Local Mode 同一目录不能被多个进程同时打开，因此索引重建采用“停止后端、运行重建脚本、再启动后端”的方式。当前 `docker-compose.yml` 不包含 Qdrant 服务；需要多实例或在线重建时，迁移到 Qdrant Server/Cloud。

Qdrant 索引是重建时快照，没有自动同步或后台任务。数据源表/字段白名单变化，指标创建、更新、删除或启停，或者查询反馈变化后，必须停止后端并重新运行 `python scripts/rebuild_knowledge_index.py`。重建前旧知识可能仍进入 Prompt，但生成的 SQL 仍不能绕过当前 SQL 校验器和表/字段白名单执行。

### Redis（未来按需）

Redis 只保存可以从 MySQL 或 Qdrant 重新生成的数据。

- Redis 不作为指标、日志、会话或数据源配置的唯一存储。
- Redis 不缓存数据库密码和完整连接地址。
- 缓存 Key 必须包含 `data_source_id`，防止跨数据源命中。
- 数据源或指标更新后需要失效对应 Schema 和查询缓存。
- Redis 不可用时，系统应回退到 MySQL/Qdrant，而不是导致核心问数链路不可用。

## 4. SQLite 与 PostgreSQL 的处理

### SQLite

当前 SQLite 仍保存平台元数据，不能直接删除。需要先把以下表迁移到 MySQL：

- `data_sources`
- `metrics`
- `query_logs`
- `chat_sessions`
- `chat_messages`

迁移和回归验证完成后，再删除 SQLite 初始化、连接和迁移兼容代码。

### PostgreSQL

PostgreSQL 不再作为默认运行依赖。可以先保留适配器和测试，但从默认 Docker Compose 启动链路中移除。只有在明确不再需要多数据源展示和兼容能力时，才完全删除驱动、客户端、文档和测试。

## 5. 分阶段实施

### 阶段一：Qdrant RAG

- 使用 `qdrant-client` Local Mode 和 `data/qdrant/`，不部署独立 Qdrant 服务。
- 使用本地 `BAAI/bge-small-zh-v1.5` 生成 512 维向量，每个 Embedding 模型对应独立 Collection。
- 导入可查询 Schema 元数据、可归属的启用指标、白名单校验通过的 SQLite 可信 SQL，以及同数据源下点赞、成功、内容完整且通过白名单校验的历史问答。
- 按 `data_source_id` 和 `queryable=true` 执行 Top-K 检索。
- 在 LangGraph 中使用 `retrieve_knowledge` 节点；无目录、无 Collection、无结果或检索/模型异常时 fail-open 回退原流程。
- 重建前停止后端，运行 `python scripts/rebuild_knowledge_index.py`，再启动后端。
- 本阶段不引入 Docker Compose Qdrant 或 Redis；多实例和在线重建需求出现后迁移到 Qdrant Server/Cloud。

### 阶段二：MySQL 元数据库

- 在 MySQL 创建 `datapilot_meta`。
- 迁移 SQLite 中的平台表和数据。
- 为元数据库建立独立读写账号。
- 把配置、日志、会话和指标访问切换到 MySQL。
- 保留一次可验证的迁移或回滚路径。

### 阶段三：收敛关系型数据库

- 删除 SQLite 运行依赖和兼容代码。
- 将 MySQL 设为默认数据源与平台元数据库。
- PostgreSQL 改为可选能力，或在确认无需求后完全删除。
- 关系型存储收敛完成后再根据实际部署需求调整 Docker 默认服务，不预设 Qdrant 容器。

### 阶段四：按需接入 Redis

只有日志或性能测试证明存在重复 Schema 获取、热门查询或会话读取瓶颈时才接入 Redis。

第一版仅实现：

- Schema TTL 缓存。
- 热门只读查询结果短 TTL 缓存。
- 数据源和指标更新时主动失效缓存。
- Redis 故障时自动回退数据库查询。

## 6. 暂不实施

- 不同时引入 Redis、Celery 和多智能体。
- 不让 Qdrant 替代关系型元数据库。
- 不把 Redis 作为持久化事实来源。
- 不在没有性能数据时实现复杂缓存一致性。
- 不在迁移完成前直接删除 SQLite。

## 7. 完成标准

- 默认部署只包含职责清晰且必要的存储组件。
- MySQL 是平台配置、日志、会话和业务数据的持久化事实来源。
- Qdrant 检索严格按数据源隔离，并能通过 eval 证明效果提升。
- Redis 可以随时清空或停用，不影响系统数据完整性和核心查询能力。
- SQLite 与 PostgreSQL 的移除不会破坏现有 API、安全策略和测试。
