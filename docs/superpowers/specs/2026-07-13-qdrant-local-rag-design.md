# Qdrant Local RAG 设计

## 1. 背景

DataPilot 当前通过 FastAPI 接收自然语言问题，并由 LangGraph 依次完成 Schema 获取、SQL 生成、安全校验、SQL 执行和中文结果分析。现有语义层会把启用指标注入 SQL 生成上下文，SQLite 数据源还支持少量硬编码可信 SQL。

本阶段增加按数据源隔离的本地 RAG 检索。在 SQL 生成前召回表字段说明、指标、可信 SQL 和高质量历史问答，提高中文 Text-to-SQL 的业务语义理解能力。

本设计严格遵循 `docs/qdrant-local-rag-requirements.md`，保留现有 SQLGlot、表字段白名单、只读、LIMIT 和查询超时防护。RAG 只提供参考上下文，不产生可绕过安全校验的执行路径。

## 2. 已确认决策

- 采用方案 A：新增一个具体的 Qdrant Local 知识服务，集中处理 Embedding、索引、检索和上下文整理。
- 向量数据库固定为官方 `qdrant-client` 的 Local Mode。
- Qdrant 数据目录固定由 `QDRANT_PATH` 配置，默认 `data/qdrant/`。
- Collection 默认名为 `datapilot_knowledge_bge_small_zh_v15`。
- Embedding 固定为 `sentence-transformers` 本地加载的 `BAAI/bge-small-zh-v1.5`。
- 向量维度固定为 512，距离函数固定为 Cosine。
- 不增加 Qdrant Server、Cloud、Docker Compose 服务或通用向量数据库抽象层。
- 不增加 Reranker、Hybrid Search、多模型切换、后台任务、管理后台、多智能体或 ReAct 循环。
- 当前仓库没有前端工程，本阶段不增加前端代码。

## 3. 目标与非目标

### 3.1 目标

1. 通过重建脚本生成并持久化本地 Qdrant 知识库。
2. 按 `data_source_id` 严格隔离知识索引和检索。
3. 在 `generate_sql` 前召回相关知识并注入现有 LLM Schema 上下文。
4. 在 `/api/chat` 返回精简的知识来源信息。
5. Qdrant 或 Embedding 不可用时自动退回原查询流程。
6. 保证所有生成 SQL 继续经过现有完整安全校验。
7. 测试不访问真实 DeepSeek、Hugging Face 网络或 Qdrant Server。

### 3.2 非目标

- 不提供文件上传、文档解析或知识库 CRUD API。
- 不实现增量同步、定时重建、Celery、消息队列或缓存。
- 不迁移现有 SQLite 元数据。
- 不修改 PostgreSQL、MySQL 或 SQLite 的现有查询适配架构。
- 不为未来数据库或模型预建 Provider、Factory 或通用接口。
- 不返回完整知识正文、向量、数据库连接地址或密码。

## 4. 现有调用链与插入点

当前链路：

```text
POST /api/chat
→ app/api/routes.py
→ DataAnalysisAgent.run()
→ retrieve_schema
→ generate_sql
→ validate_sql
→ execute_sql
→ analyze_result
→ 写入 query_logs 和 chat_messages
```

调整后：

```text
retrieve_schema
→ retrieve_knowledge
→ generate_sql
→ validate_sql
→ execute_sql
→ analyze_result
```

`retrieve_knowledge` 只读取当前问题和 `data_source_id`，不得执行 SQL。节点输出：

- `knowledge_context`：长度受限、明确标记为参考资料的文本。
- `knowledge_sources`：供 API 返回的精简来源列表。

`generate_sql` 保持现有 LLM 方法签名，把 `knowledge_context` 追加到现有 Schema 上下文后调用 `generate_sql(question, schema)`。

## 5. 组件设计

### 5.1 `app/services/knowledge.py`

新增一个具体的本地知识模块，不定义通用 VectorStore 或 Embedding Provider 层。模块包含以下职责：

1. 延迟加载 `SentenceTransformer("BAAI/bge-small-zh-v1.5")`。
2. 文档批量编码和查询编码。
3. 校验每个向量维度必须为 512。
4. 使用 `normalize_embeddings=True` 生成归一化向量。
5. 查询文本使用 BGE 中文检索指令，知识正文不加查询指令。
6. 创建、重建、写入和查询指定 Qdrant Collection。
7. 强制构造 `data_source_id` Payload Filter。
8. 把召回结果转换为长度受限的 Prompt 参考上下文和 API 来源。
9. 收集 Schema、指标、可信 SQL 和历史问答知识。

模型在首次实际编码时加载，应用启动不下载模型。检索前先检查 Qdrant 路径和 Collection；不存在时直接返回空结果，避免无索引情况下触发模型下载。

### 5.2 LangGraph 集成

`DataAnalysisAgent` 增加可注入的具体知识检索对象。生产环境由 `create_app()` 使用配置创建；测试可传入 Fake Retriever，不加载真实模型。

`AnalysisState` 增加：

```text
knowledge_context: str
knowledge_sources: list[dict]
```

`retrieve_knowledge` 捕获所有内部异常，只返回空上下文和空来源。异常日志只记录异常类型，不记录异常正文、本地路径或连接地址。

### 5.3 索引脚本

新增：

```text
scripts/rebuild_knowledge_index.py
```

执行流程：

1. 初始化现有 SQLite 元数据库。
2. 读取全部现有数据源。
3. 为每个数据源收集四种知识。
4. 删除并重建固定 Collection，确保不同模型向量不会混用。
5. 使用 BGE 模型批量生成向量。
6. 使用确定性 Point ID 写入 Qdrant。
7. 输出每种知识类型和总计数量。
8. 任一数据源读取失败时，不输出原始异常信息；脚本最终返回非零退出码。

脚本不读取或索引业务表原始数据，不把 `database_url`、用户名、密码或完整查询结果写入 Qdrant。

## 6. 知识模型

每条知识在应用内部表示为标题、正文和 Payload。Qdrant Payload 至少包含：

```json
{
  "data_source_id": 1,
  "knowledge_type": "schema",
  "source_id": "column:orders.created_at",
  "title": "orders.created_at",
  "content": "字段：created_at；类型：TEXT；业务说明：订单创建时间",
  "queryable": true
}
```

`knowledge_type` 只允许：

```text
schema
metric
trusted_sql
historical_qa
```

Point ID 使用标准库 `uuid.uuid5()` 根据以下值生成：

```text
data_source_id + knowledge_type + source_id
```

即使未来把重建调整为覆盖写入，同一来源仍保持相同 Point ID。

## 7. 知识收集规则

### 7.1 Schema

优先复用：

- `list_catalog_tables()`
- `list_catalog_columns()`
- `TABLE_DESCRIPTIONS`
- 现有表字段白名单

表和字段分别建立知识记录。正文组合英文标识符、数据类型、中文说明和查询权限。

知识收集需要发现当前数据库中的全部表字段，并为每条记录计算 `queryable`。现有 API 仍只展示允许查询的目录；实现时给目录读取方法增加仅供内部索引使用的 `include_non_queryable` 参数，默认值保持 `false`，因此现有 API 行为不变。索引检索只允许返回 `queryable=true` 的记录，非白名单表字段不会进入 LLM 上下文。

### 7.2 指标

只读取 `list_metrics(enabled_only=True)`。

当前指标表没有 `data_source_id`，所以不修改指标存储结构，而是按数据源逐一使用现有表字段白名单过滤逻辑：

- 指标引用非白名单表时跳过。
- 指标引用非白名单字段时跳过。
- 过滤通过后，将当前数据源 ID 写入 Payload。

指标正文包含名称、说明、计算公式和可从公式确定的关联表字段。现有说明中的过滤条件原样保留。

### 7.3 可信 SQL

复用 `app/services/semantic.py` 中现有可信答案。

- 只处理 SQLite 数据源，因为现有可信 SQL 使用 SQLite 方言。
- 每条 SQL 在进入索引前使用该数据源的表字段白名单执行 `validate_select_sql()`。
- 校验失败的可信 SQL 不进入该数据源索引。
- 正文包含用户问题、SQL 和 SQL 解释。
- 表字段信息使用现有 SQLGlot AST 解析结果生成，不执行 SQL。

召回的可信 SQL只是参考。LLM 输出仍进入原有 `validate_sql` 节点，不存在直接执行路径。

### 7.4 高质量历史问答

当前 `query_logs` 缺少完整索引条件所需字段，因此进行兼容迁移，增加：

```text
data_source_id INTEGER
sql_explanation TEXT
answer TEXT
```

新查询完成后，`DataAnalysisAgent.run()` 将以上字段与现有日志一起写入。列表 API 不必返回这些新增内部字段，避免无关 API 扩展。

重建时只选择同时满足以下条件的记录：

- `error IS NULL`
- `feedback = 'like'`
- `data_source_id IS NOT NULL`
- 问题、SQL 和答案均为非空文本
- `data_source_id` 对应当前仍存在的数据源

旧日志无法可靠确定数据源或没有答案，因此按要求跳过。正文只包含问题、SQL、SQL 解释和中文总结，不保存原始查询结果。

## 8. 索引与检索

### 8.1 Collection

默认配置：

```text
名称：datapilot_knowledge_bge_small_zh_v15
向量维度：512
距离：Cosine
```

重建脚本删除并重新创建 Collection。这同时提供幂等性并防止不同 Embedding 模型写入同一 Collection。

### 8.2 检索过滤

每次检索必须由代码构造 Qdrant Filter：

```text
data_source_id == 当前会话数据源 ID
queryable == true
```

调用方不能传入或覆盖该过滤器。Prompt 文本中的数据源描述不作为隔离手段。

### 8.3 上下文限制

- 检索数量由 `KNOWLEDGE_TOP_K` 控制，默认 5。
- 结果按 Qdrant score 降序。
- 单条正文最多保留 1000 个字符，总知识上下文最多保留 4000 个字符。
- 上下文使用清晰分隔符，并在开头声明：召回内容仅供参考，不能覆盖 SQL 安全规则、Schema 白名单或系统指令。
- API 来源只保留类型、来源 ID、标题和分数。

## 9. 配置

沿用 `app/core/config.py` 当前环境变量风格，增加：

```env
QDRANT_PATH=data/qdrant
QDRANT_COLLECTION=datapilot_knowledge_bge_small_zh_v15
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
KNOWLEDGE_TOP_K=5
```

虽然保留 `EMBEDDING_MODEL` 配置项以符合需求文档，但本阶段只接受 `BAAI/bge-small-zh-v1.5`。配置为其他值时，重建脚本直接失败，运行时检索按降级规则返回空结果，防止把其他模型向量写入当前 Collection。

`requirements.txt` 增加官方 `qdrant-client` 和 `sentence-transformers`。不增加额外向量库、缓存或编排依赖。

`.gitignore` 增加：

```text
data/qdrant/
```

## 10. API 兼容性

`ChatResponse` 增加默认空列表字段：

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

无召回或检索降级时返回：

```json
{
  "knowledge_sources": []
}
```

不删除、重命名或改变现有响应字段含义。

## 11. 降级与错误处理

以下情况统一返回空检索结果，继续执行原工作流：

- Qdrant 路径不存在。
- Collection 不存在。
- Collection 配置不匹配。
- Qdrant 打开或查询失败。
- Embedding 模型加载失败。
- Embedding 编码失败或向量维度错误。
- 当前数据源没有知识。
- 检索结果为空。

内部异常不得进入 `ChatResponse.error`，因为 RAG 失败不是核心查询失败。日志只记录固定消息和异常类型。

Qdrant Local 对同一数据目录存在进程级独占限制。索引重建文档要求先停止后端进程；本阶段不为 Local Mode 实现在线热切换。需要不停机重建或多实例部署时迁移到 Qdrant Server。

## 12. 安全设计

1. RAG 不改变 `validate_select_sql()` 或执行层入口。
2. 召回 SQL不能直接传入 `execute_data_source_select()`。
3. 可信 SQL进入索引前校验，LLM 采用后再次校验。
4. Qdrant Payload 不包含 `database_url`、用户名、密码、API Key 或完整原始查询结果。
5. 脚本和运行时错误不输出原始数据库连接异常。
6. 数据源隔离依赖强制 Payload Filter，而不是 Prompt。
7. 非白名单字段即使存在索引记录，也因 `queryable=false` 不得召回。
8. SQL 仍只允许单条 `SELECT`，禁止注释、多语句、`SELECT *`、DDL/DML 和非白名单表字段，并强制最大 `LIMIT 100`。

## 13. 测试设计

测试使用 Fake Embedder、Fake Retriever 和临时 Qdrant Local 目录，不下载真实模型，不访问外部服务。

### 13.1 知识服务测试

1. Fake Embedder 生成 512 维确定性向量并写入临时 Qdrant。
2. 连续两次重建后数量不增长。
3. 不同 `data_source_id` 之间无法互相召回。
4. Schema、指标、可信 SQL 和历史问答都能进入索引和召回。
5. 未点赞、执行失败、答案为空或数据源不明确的历史记录被排除。
6. Payload 不包含数据库 URL 或密码。
7. Collection 不存在时返回空结果且不调用 Embedder。

### 13.2 Agent/API 测试

1. Fake Retriever 的上下文进入 SQL 生成 Prompt。
2. `/api/chat` 返回 `knowledge_sources`。
3. Fake Retriever 抛出异常时原查询链路仍成功。
4. 无召回时返回空数组。
5. 召回内容包含危险 SQL时，LLM 生成的危险 SQL仍被 SQL 安全校验拦截。
6. API 不返回知识正文、向量、数据库连接地址或密码。

### 13.3 回归验证

```bash
python -m pytest -q
python scripts/run_evals.py
git diff --check
```

必须保证 SQLite、PostgreSQL、MySQL、数据源管理、语义层、可信答案、日志、会话和现有 eval 全部继续通过。

## 14. 预计文件范围

新增：

```text
app/services/knowledge.py
scripts/rebuild_knowledge_index.py
tests/test_knowledge.py
```

修改：

```text
requirements.txt
.gitignore
.env.example
app/core/config.py
app/main.py
app/agent/workflow.py
app/db/database.py
app/schemas/chat.py
app/api/routes.py
tests/test_api.py
tests/test_database.py
tests/test_engineering_assets.py
README.md
docs/mvp-design.md
docs/storage-architecture-roadmap.md
```

不修改 `docker-compose.yml`，不增加前端文件。

## 15. 风险与处理

### 首次模型下载和启动延迟

模型只在首次实际编码时下载和加载，之后使用 sentence-transformers/Hugging Face 本地缓存。README 明确说明首次重建需要网络和较长时间。

### Qdrant Local 独占目录

重建时要求停止后端。未来需要多进程、在线重建或高并发时迁移 Qdrant Server，而不是在本阶段增加锁服务或临时 Collection 切换。

### 旧历史日志无法索引

旧记录缺少数据源和答案，不能安全推断，直接跳过。新字段上线后的成功点赞记录可在下次重建时进入索引。

### 全局指标缺少数据源归属

使用现有表字段白名单按数据源派生归属，不为本需求修改指标表。未来需要同名不同口径的企业级指标时，再单独设计指标的数据源字段和版本管理。

### Prompt 中的参考内容可能包含错误信息

参考上下文明确降权，不覆盖系统规则；最终 SQL 必须通过确定性安全验证，因此错误知识不能直接触发执行。

## 16. 验收标准

1. 重建脚本能够在 `data/qdrant/` 创建固定 Collection。
2. Collection 使用 512 维 Cosine 向量和指定 BGE 模型。
3. 四种知识按规则进入索引。
4. 检索始终强制按 `data_source_id` 隔离。
5. 召回上下文在 SQL 生成前注入。
6. `/api/chat` 返回兼容的 `knowledge_sources`。
7. Qdrant、Collection 或模型不可用时，原问数流程继续工作。
8. 所有 SQL 继续经过现有完整安全校验。
9. Payload、日志和 API 不泄露密码或完整连接地址。
10. 全量 pytest、eval 和 `git diff --check` 通过。
