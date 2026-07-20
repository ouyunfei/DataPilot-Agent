# DataPilot Agent

基于 LangGraph 的智能数据分析 Agent。用户用自然语言提出业务数据问题，系统自动完成表结构理解、DeepSeek SQL 生成、SQL 安全校验、SQL 执行和中文分析总结。

这个项目不是普通聊天机器人，而是面向业务数据查询和分析场景的后端 Agent。当前版本默认接入 DeepSeek，SQLite 示例库包含 `orders`、`users`、`products` 三张表，并使用 SQLGlot 做 AST 级 SQL 安全校验。

## 功能特性

- FastAPI 后端服务
- LangGraph 编排数据分析工作流
- DeepSeek 生成 SQL、SQL 解释和中文分析结论
- SQLite 自动初始化订单、用户、商品三张示例表
- PostgreSQL / MySQL 真实数据源接入，Docker 提供本地示例库
- SQLGlot AST 安全校验
- 强制 `LIMIT`，最大返回 100 行
- 禁止 `SELECT *` 和非白名单表访问
- 数据源管理：支持 SQLite / MySQL / PostgreSQL 连接、目录读取和只读查询
- 表权限白名单：每个数据源独立配置允许查询的表
- 字段级权限白名单：每个数据源独立配置允许查询的字段
- 数据目录接口：查看可查询表、字段、字段类型和字段说明
- 查询保护增强：SQL 执行超时、错误分类和日志记录
- 指标管理：用 SQLite 配置销售额、退款率、客单价、毛利、订单数等业务口径
- 语义层把启用指标动态注入给 Agent
- 高频问题优先命中可信 SQL
- Qdrant Local 本地 RAG：按 `data_source_id` 隔离 Schema、指标、可信 SQL 和高质量历史问答四类知识
- 本地 `BAAI/bge-small-zh-v1.5` Embedding；知识库不可用或无召回时 fail-open 回退原查询流程
- SQLite 记录查询日志，便于后续运营和优化
- 查询日志列表和用户反馈接口
- 多轮追问：返回并复用 `session_id`，把最近会话上下文注入 SQL 生成
- 查询统计接口：统计成功率、失败数、图表类型分布和高频问题
- 健康检查返回数据库和 DeepSeek 配置状态，不暴露 API key
- 安全策略自检接口，便于展示 SQL 防护规则
- 根据结果字段推荐图表类型
- 异常 / 趋势发现：自动识别峰值、明显下降、退款率异常和 Top 差距
- Docker 一键启动
- GitHub Actions 自动运行测试
- 离线确定性 eval 验证 Text-to-SQL 工程链路；可选真实 RAG A/B 单独衡量效果
- `POST /api/chat` 返回 SQL、SQL 解释、查询数据、中文分析结论和错误信息
- 单元测试覆盖 SQL 安全、数据库初始化和接口调用

## 项目结构

```text
DataPilot-Agent/
├── app/
│   ├── agent/
│   │   └── workflow.py          # LangGraph 数据分析工作流
│   ├── api/
│   │   └── routes.py            # FastAPI 路由
│   ├── core/
│   │   └── config.py            # 配置和环境变量
│   ├── db/
│   │   ├── database.py          # SQLite 初始化、数据源、日志、schema 获取、查询执行
│   │   ├── mysql.py             # MySQL 连接、目录读取、查询执行
│   │   └── postgres.py          # PostgreSQL 连接、目录读取、查询执行
│   ├── schemas/
│   │   └── chat.py              # Pydantic 请求/响应模型
│   ├── services/
│   │   ├── knowledge.py         # Qdrant Local 知识构建、检索和本地 BGE Embedding
│   │   ├── llm.py               # DeepSeek LLM 客户端
│   │   ├── semantic.py          # 语义层上下文、可信答案和图表推荐
│   │   ├── insights.py          # 异常 / 趋势洞察规则
│   │   └── sql_validator.py     # SQLGlot 安全校验
│   └── main.py                  # FastAPI 应用入口
├── docs/
│   ├── mvp-design.md
│   ├── qdrant-local-rag-requirements.md
│   ├── storage-architecture-roadmap.md
│   └── superpowers/
├── evals/
│   └── questions.json          # Text-to-SQL 评测问题集
├── scripts/
│   ├── rebuild_knowledge_index.py # 重建本地知识索引
│   ├── run_evals.py              # 离线确定性 eval 与合成 RAG wiring smoke
│   └── run_rag_ab_eval.py        # 可选的真实 DeepSeek RAG off/on A/B
├── tests/
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── docker/mysql/init.sql        # MySQL 示例库初始化脚本
├── docker/postgres/init.sql     # PostgreSQL 示例库初始化脚本
├── .env.example
└── requirements.txt
```

## 工作流设计

```text
retrieve_schema -> retrieve_knowledge -> generate_sql -> validate_sql -> execute_sql -> analyze_result
```

节点职责：

- `retrieve_schema`：读取三张表结构、字段说明、表关系和启用指标口径
- `retrieve_knowledge`：按当前 `data_source_id` 召回可查询知识；失败或无结果时返回空上下文继续执行
- `generate_sql`：调用 DeepSeek，根据用户问题和 schema 生成 SQL 与 SQL 解释
- `validate_sql`：使用 SQLGlot 校验 SQL 安全性，并强制 `LIMIT`
- `execute_sql`：执行已校验 SQL 并返回查询结果
- `analyze_result`：调用 DeepSeek，基于查询结果和规则洞察生成中文业务分析结论

如果 `validate_sql` 发现危险 SQL，工作流会直接跳过 `execute_sql`，返回错误信息。

## 数据库设计

启动时自动创建 `data/datapilot.db`，并初始化示例数据。

`users` 用户维度表：

| 字段 | 说明 |
| --- | --- |
| `id` | 用户 ID |
| `name` | 用户姓名 |
| `city` | 常驻城市 |
| `level` | 用户等级 |
| `registered_at` | 注册日期 |

`products` 商品维度表：

| 字段 | 说明 |
| --- | --- |
| `id` | 商品 ID |
| `product_name` | 商品名称 |
| `category` | 商品品类 |
| `brand` | 品牌 |
| `cost_price` | 成本价 |
| `list_price` | 标价 |

`orders` 订单事实表：

| 字段 | 说明 |
| --- | --- |
| `id` | 订单 ID |
| `user_id` | 用户 ID，关联 `users.id` |
| `product_id` | 商品 ID，关联 `products.id` |
| `product_name` | 商品名称 |
| `category` | 商品品类 |
| `city` | 订单城市 |
| `amount` | 订单金额 |
| `status` | 订单状态 |
| `created_at` | 下单时间 |
| `refund_amount` | 退款金额 |

`metrics` 指标配置表默认初始化销售额、退款率、客单价、毛利和订单数。启用状态的指标会被注入 Agent 的语义层：

| 字段 | 说明 |
| --- | --- |
| `metric_key` | 指标唯一标识 |
| `name` | 指标中文名 |
| `expression` | 指标计算口径 |
| `description` | 业务说明 |
| `enabled` | 是否启用 |

## 本地启动

建议使用虚拟环境：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

复制配置文件：

```bash
copy .env.example .env
```

在 `.env` 中填写 DeepSeek API key：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT_SECONDS=30
QUERY_TIMEOUT_SECONDS=5
POSTGRES_EXAMPLE_URL=postgresql://datapilot:datapilot123@127.0.0.1:5432/datapilot
QDRANT_PATH=data/qdrant
QDRANT_COLLECTION=datapilot_knowledge_bge_small_zh_v15
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
KNOWLEDGE_TOP_K=5
```

启动服务：

```bash
uvicorn app.main:app --reload
```

默认访问：

- 健康检查：http://127.0.0.1:8000/health
- Swagger 文档：http://127.0.0.1:8000/docs

## Local RAG

依赖已经包含在 `requirements.txt`，安装方式仍是：

```bash
pip install -r requirements.txt
```

索引包含四类知识：

- `schema`：数据源的表和字段元数据；不可查询项会标记 `queryable=false`，检索只召回白名单允许的元数据。
- `metric`：启用且表达式能归属到当前数据源白名单表、字段的指标。
- `trusted_sql`：通过当前 SQLite 数据源表、字段白名单校验的可信 SQL。
- `historical_qa`：当前 `data_source_id` 下已点赞、执行成功且问题、SQL、回答完整，并通过当前数据源表/字段白名单校验的历史问答；旧日志缺少数据源或完整内容时跳过。

配置：

```env
QDRANT_PATH=data/qdrant
QDRANT_COLLECTION=datapilot_knowledge_bge_small_zh_v15
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
KNOWLEDGE_TOP_K=5
```

停止后端后重建索引：

```bash
python scripts/rebuild_knowledge_index.py
```

脚本重建 Collection，并输出 `schema`、`metric`、`trusted_sql`、`historical_qa` 和 `total` 数量。首次运行会从 Hugging Face 下载 `BAAI/bge-small-zh-v1.5`，后续使用本地缓存；模型固定生成 512 维向量，Qdrant 使用 Cosine 距离，不调用外部 Embedding API，也不支持运行时切换模型。不同模型必须使用不同 Collection 并重建索引。

Qdrant 索引是重建时快照，没有自动同步或后台任务。数据源表/字段白名单变化，指标创建、更新、删除或启停，或者查询反馈变化后，都要先停止后端，再运行 `python scripts/rebuild_knowledge_index.py`。重建前旧知识可能仍进入 Prompt，但生成的 SQL 仍不能绕过当前 SQL 校验器和表/字段白名单执行。

Qdrant Local 数据保存在 `data/qdrant/`，该目录已被 Git 忽略。需要清理时，先停止后端，再删除整个 `data/qdrant/` 目录并运行重建命令。Local Mode 的同一目录不能被多个进程同时打开，因此后端运行时不要重建；需要多实例或在线重建时迁移到 Qdrant Server/Cloud。本阶段 `docker-compose.yml` 不启动 Qdrant 服务。

每次检索都使用 Qdrant Payload Filter 强制限定当前 `data_source_id` 和 `queryable=true`。召回内容只作为长度受限的参考上下文，不能覆盖 SQL 安全规则；所有 SQL 仍经过 SQLGlot、表/字段白名单、只读、`LIMIT 100` 和执行超时保护。

知识目录或 Collection 不存在、Qdrant 查询失败、Embedding 模型加载失败、当前数据源无知识或检索结果为空时，系统自动使用空知识上下文继续原流程。客户端只看到空 `knowledge_sources`，不会收到内部异常类型、本地路径、知识正文、向量或连接密钥。

可选的真实 RAG A/B 运行前必须满足：

- 已配置可用的 DeepSeek API key、模型和地址。
- `DEFAULT_DATABASE_PATH` 指向的默认数据库已存在。
- 数据源 ID 1 存在，且是默认 SQLite 数据源。
- `QDRANT_COLLECTION` 已使用当前 `EMBEDDING_MODEL` 构建，非空，并且是 512 维、Cosine 距离。
- 后端和其他占用 `QDRANT_PATH` 的进程已经停止；运行期间不能并发打开同一个 Qdrant Local Mode 目录。

运行：

```bash
python scripts/run_rag_ab_eval.py
```

该脚本复制默认 SQLite 数据库到临时目录，用真实 DeepSeek 分别运行两个完整 Agent：`off` 不启用知识检索，`on` 使用真实 BGE/Qdrant 检索；两组均执行生成 SQL，并按参考结果评分。它依赖本地配置和模型输出，不进入 CI。结果应如实报告为正向、持平或负向，单次结果不能外推为长期保证。

最近一次真实运行（2026-07-20）结果为 `off 3/3`、`on 3/3`、`Delta: tie`，尚未证明 RAG 带来质量提升。

## Docker 启动

先复制配置文件：

```bash
copy .env.example .env
```

如需真实调用 DeepSeek，在 `.env` 中填入自己的 API key。不要把 `.env` 提交到 GitHub。

启动：

```bash
docker compose up --build
```

只启动本地 PostgreSQL 示例库：

```bash
docker compose up -d postgres
```

只启动本地 MySQL 示例库：

```bash
docker compose up -d mysql
```

启动后访问：

- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/docs

## 接口示例

### 自然语言问数

请求：

```bash
curl -X POST "http://127.0.0.1:8000/api/chat" ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"最近 30 天销售额最高的 5 个商品是什么？\"}"
```

响应示例：

```json
{
  "question": "最近 30 天销售额最高的 5 个商品是什么？",
  "session_id": "0b6f6a50-6f8d-4b2f-a1af-b1f8db663ab4",
  "data_source_id": 1,
  "sql": "SELECT product_name, ROUND(SUM(amount), 2) AS total_amount, COUNT(*) AS order_count FROM orders WHERE status = 'paid' GROUP BY product_name ORDER BY total_amount DESC LIMIT 5",
  "sql_explanation": "按商品名称分组，统计已支付订单销售额，并按销售额倒序取前 5 名。",
  "data": [
    {
      "product_name": "人体工学椅",
      "total_amount": 13311.55,
      "order_count": 8
    }
  ],
  "chart": {
    "type": "bar",
    "x": "product_name",
    "y": "total_amount",
    "reason": "排行或对比数据适合柱状图。"
  },
  "insights": [
    {
      "type": "gap",
      "message": "Top 1 人体工学椅 比 Top 2 咖啡机 高 28.0%，头部差距明显。"
    }
  ],
  "knowledge_sources": [
    {
      "knowledge_type": "metric",
      "source_id": "1",
      "title": "销售额",
      "score": 0.87
    }
  ],
  "trusted_answer": true,
  "answer": "最近 30 天销售额最高的 Top 5 商品分别是人体工学椅、咖啡机、冲锋衣、空气炸锅和智能电饭煲，其中人体工学椅排名第一。Top 1 人体工学椅 比 Top 2 咖啡机 高 28.0%，头部差距明显。",
  "error": null,
  "error_code": null
}
```

`knowledge_sources` 只返回 `knowledge_type`、`source_id`、`title` 和 `score`，不返回知识正文、向量、数据库地址或密钥。没有召回或 Local RAG 降级时返回：

```json
{
  "knowledge_sources": []
}
```

指定数据源时，在请求中加入 `data_source_id`；不传则使用默认 SQLite 示例数据源：

```json
{
  "question": "最近 30 天销售额最高的 5 个商品是什么？",
  "data_source_id": 1
}
```

多轮追问时，把上一次响应里的 `session_id` 带回去：

```json
{
  "question": "那按城市拆开看呢？",
  "session_id": "0b6f6a50-6f8d-4b2f-a1af-b1f8db663ab4"
}
```

可测试问题：

- 最近 30 天销售额最高的 5 个商品是什么？
- 哪个商品品类的退款率最高？
- 最近一个月每天的销售额趋势如何？
- 不同城市的订单金额排名如何？
- 哪些用户的消费金额最高？
- 哪个用户等级的客单价最高？
- 哪个品牌的销售额最高？

危险 SQL 拦截示例：

```bash
curl -X POST "http://127.0.0.1:8000/api/chat" ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"请删除所有订单数据\"}"
```

系统会返回错误信息，并且不会执行数据库查询。

### 查询日志

```bash
curl "http://127.0.0.1:8000/api/query-logs"
```

返回最近查询的问题、SQL、命中可信答案情况、图表类型、行数、错误、耗时和创建时间。

### 查询统计

```bash
curl "http://127.0.0.1:8000/api/query-stats"
```

返回总查询数、成功数、失败数、可信答案命中数、平均耗时、图表类型分布、反馈分布和高频问题，用于展示 Agent 的运营监控能力。

### 用户反馈

```bash
curl -X POST "http://127.0.0.1:8000/api/query-logs/1/feedback" ^
  -H "Content-Type: application/json" ^
  -d "{\"feedback\":\"like\",\"note\":\"结果准确\"}"
```

`feedback` 只支持 `like` 或 `dislike`，用于沉淀后续优化样本。

### 安全策略自检

```bash
curl "http://127.0.0.1:8000/api/security/policies"
```

返回当前 SQL 安全策略，例如只允许 `SELECT`、禁止多语句、禁止 `SELECT *`、白名单表、白名单字段、最大 `LIMIT` 和查询超时。

### 数据源管理

```bash
curl "http://127.0.0.1:8000/api/data-sources"
```

创建数据源：

```bash
curl -X POST "http://127.0.0.1:8000/api/data-sources" ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"orders_only\",\"db_type\":\"sqlite\",\"database_url\":\"data/datapilot.db\",\"allowed_tables\":[\"orders\"],\"allowed_columns\":{\"orders\":[\"id\",\"product_name\",\"amount\",\"created_at\"]}}"
```

测试数据源：

```bash
curl -X POST "http://127.0.0.1:8000/api/data-sources/1/test"
```

更新连接地址、白名单或默认状态：

```bash
curl -X PUT "http://127.0.0.1:8000/api/data-sources/2" ^
  -H "Content-Type: application/json" ^
  -d "{\"allowed_tables\":[\"orders\"],\"allowed_columns\":{\"orders\":[\"id\",\"amount\",\"created_at\"]},\"is_default\":true}"
```

删除非默认数据源：

```bash
curl -X DELETE "http://127.0.0.1:8000/api/data-sources/2"
```

当前默认数据源不能直接取消默认状态或删除，需要先把其他数据源设置为默认。更新响应和列表响应会继续隐藏连接密码，脱敏后的 `***` 地址不能作为更新值提交。

SQLite、PostgreSQL 和 MySQL 数据源都会真实检查白名单表和字段，并支持 `/api/chat` 只读查询。MySQL 数据源必须显式提供每张白名单表的 `allowed_columns`。

本地 Docker PostgreSQL 示例库连接串：

```text
postgresql://datapilot:datapilot123@127.0.0.1:5432/datapilot
```

如果后端也运行在 `docker compose` 容器内，使用服务名：

```text
postgresql://datapilot:datapilot123@postgres:5432/datapilot
```

创建 PostgreSQL 数据源：

```bash
curl -X POST "http://127.0.0.1:8000/api/data-sources" ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"local_postgres\",\"db_type\":\"postgresql\",\"database_url\":\"postgresql://datapilot:datapilot123@127.0.0.1:5432/datapilot\",\"allowed_tables\":[\"orders\",\"users\",\"products\"],\"allowed_columns\":{\"orders\":[\"id\",\"user_id\",\"product_id\",\"product_name\",\"category\",\"city\",\"amount\",\"status\",\"created_at\",\"refund_amount\"],\"users\":[\"id\",\"name\",\"city\",\"level\",\"registered_at\"],\"products\":[\"id\",\"product_name\",\"category\",\"brand\",\"cost_price\",\"list_price\"]}}"
```

测试 PostgreSQL 数据源：

```bash
curl -X POST "http://127.0.0.1:8000/api/data-sources/{id}/test"
```

指定 PostgreSQL 数据源问数：

```json
{
  "question": "最近 30 天销售额最高的 5 个商品是什么？",
  "data_source_id": 2
}
```

本地 Docker MySQL 示例库连接串：

```text
mysql://datapilot_ro:datapilot123@127.0.0.1:3307/datapilot
```

如果后端运行在 `docker compose` 容器内，连接地址使用 `mysql://datapilot_ro:datapilot123@mysql:3306/datapilot`。宿主机端口默认是 `3307`，可通过 `MYSQL_PORT` 覆盖。

创建 MySQL 数据源：

```bash
curl -X POST "http://127.0.0.1:8000/api/data-sources" ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"local_mysql\",\"db_type\":\"mysql\",\"database_url\":\"mysql://datapilot_ro:datapilot123@127.0.0.1:3307/datapilot\",\"allowed_tables\":[\"orders\",\"users\",\"products\"],\"allowed_columns\":{\"orders\":[\"id\",\"user_id\",\"product_id\",\"product_name\",\"category\",\"city\",\"amount\",\"status\",\"created_at\",\"refund_amount\"],\"users\":[\"id\",\"name\",\"city\",\"level\",\"registered_at\"],\"products\":[\"id\",\"product_name\",\"category\",\"brand\",\"cost_price\",\"list_price\"]}}"
```

创建和列表接口会把连接密码显示为 `***`。本地初始化脚本负责建表和造数，Agent 查询链路仍然只允许执行 `SELECT`；接入真实数据库时应使用只读账号。

### 数据目录

查看当前数据源可查询表：

```bash
curl "http://127.0.0.1:8000/api/catalog/tables"
```

查看字段目录和字段权限：

```bash
curl "http://127.0.0.1:8000/api/catalog/tables/products/columns"
```

指定数据源：

```bash
curl "http://127.0.0.1:8000/api/catalog/tables/products/columns?data_source_id=1"
```

### 指标管理

```bash
curl "http://127.0.0.1:8000/api/metrics"
```

新增指标：

```bash
curl -X POST "http://127.0.0.1:8000/api/metrics" ^
  -H "Content-Type: application/json" ^
  -d "{\"metric_key\":\"repeat_order_count\",\"name\":\"复购订单数\",\"expression\":\"COUNT(orders.id)\",\"description\":\"重复购买订单数量。\"}"
```

禁用指标：

```bash
curl -X PUT "http://127.0.0.1:8000/api/metrics/1" ^
  -H "Content-Type: application/json" ^
  -d "{\"enabled\":false}"
```

## SQL 安全策略

SQL 执行前必须通过 `validate_sql`：

- 只允许单条 `SELECT`
- 禁止 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`TRUNCATE`
- 禁止注释和多语句
- 禁止 `SELECT *`
- 只允许访问当前数据源配置的白名单表
- 只允许访问当前数据源配置的白名单字段
- 没有 `LIMIT` 时自动追加 `LIMIT 100`
- `LIMIT` 超过 100 时自动收敛为 `LIMIT 100`
- SQLite / PostgreSQL / MySQL 查询执行默认超时时间为 `QUERY_TIMEOUT_SECONDS=5`
- 使用 SQLGlot 做 AST 级别校验

## 语义层、可信答案、查询日志、图表推荐和洞察

后端会从 `metrics` 表读取启用指标并注入给 DeepSeek；常见问题命中可信 SQL；每次查询写入 `query_logs`；接口返回 `chart` 字段给未来前端使用。数据源白名单会同时作用于 schema 注入和 SQL 安全校验。

`insights` 字段使用确定性规则生成，不让 LLM 编造异常结论。当前支持：

- 日期趋势中的最高值
- 相邻日期下降超过 30% 的明显波动
- 品类退款率明显高于平均水平
- Top 1 和 Top 2 差距是否明显

## 运行测试

```bash
python -m pytest -q
```

## eval 评测集

评测集位于：

```text
evals/questions.json
```

运行：

```bash
python scripts/run_evals.py
```

脚本使用临时 SQLite 和 fake LLM，不依赖真实 DeepSeek、Hugging Face 或已构建的 Qdrant Collection，因此是可在 CI/离线环境运行的确定性工程检查。它会检查 SQL 是否生成、安全校验是否通过、返回字段是否符合预期、图表类型是否正确。

脚本同时包含一组 fake LLM + fake retriever 的配对 RAG 检查，只证明知识上下文已接入 Agent 工作流且能影响固定 SQL；这是合成 wiring smoke，不是真实模型质量基准。真实效果比较使用上文可选的 `python scripts/run_rag_ab_eval.py`，其结果不作为 CI 稳定门禁。

示例输出：

```text
Eval passed: 7/7
Success rate: 100.00%
```

## GitHub Actions CI

CI 配置位于：

```text
.github/workflows/ci.yml
```

每次 `push` 或 `pull_request` 会自动执行：

```bash
python -m pytest -q
```

测试使用 fake LLM，不需要配置真实 DeepSeek API key。

## 秋招展示脚本

1. 启动项目：

```bash
uvicorn app.main:app --reload
```

2. 打开 Swagger 或 Postman，先访问：

```text
GET http://127.0.0.1:8000/health
```

说明项目启动后会自动初始化 SQLite，并且健康检查只返回 `deepseek_configured`，不会泄漏 API key。

3. 演示自然语言问数：

```text
POST http://127.0.0.1:8000/api/chat
Content-Type: application/json

{
  "question": "最近 30 天销售额最高的 5 个商品是什么？"
}
```

讲解链路：LangGraph 获取 schema 和语义层，按数据源召回 Local RAG 参考知识，SQLite 高频问题优先命中可信 SQL，经过 SQLGlot 安全校验后执行 SQLite、PostgreSQL 或 MySQL 查询，再生成中文 Top 5 总结、规则洞察和图表推荐。

4. 演示危险 SQL 拦截：

```json
{
  "question": "请删除所有订单数据"
}
```

说明所有 SQL 在执行前必须经过安全校验，不安全时直接返回 `error`，不会查询数据库。

5. 演示可运营闭环：

```text
GET http://127.0.0.1:8000/api/query-logs
GET http://127.0.0.1:8000/api/query-stats
GET http://127.0.0.1:8000/api/data-sources
GET http://127.0.0.1:8000/api/catalog/tables
GET http://127.0.0.1:8000/api/catalog/tables/products/columns
GET http://127.0.0.1:8000/api/metrics
POST http://127.0.0.1:8000/api/query-logs/{id}/feedback
GET http://127.0.0.1:8000/api/security/policies
```

讲解查询日志和统计接口用于观察高频问题、失败问题、慢查询和图表使用分布，数据源白名单和字段白名单用于限制可查询数据范围，数据目录用于展示表字段元数据，指标管理让语义层从硬编码升级为可配置，用户反馈用于沉淀可信答案和优化语义层。

6. 演示工程化能力：

```text
docker compose up --build
docker compose up -d postgres
docker compose up -d mysql
python -m pytest -q
python scripts/run_evals.py
```

讲解 Docker 解决环境一致性，GitHub Actions 保证提交后自动测试；离线确定性 eval 检查工程链路，真实 DeepSeek RAG A/B 则单独报告正向、持平或负向结果。

## 后续扩展方向

- Local RAG 需要多实例或在线重建时迁移到 Qdrant Server/Cloud
- 加入 Redis：缓存 schema、热门查询结果和会话上下文
- 加入 Celery：处理耗时查询、异步报表和定时分析任务
- 多智能体拆分：Schema Agent、SQL Agent、SQL Review Agent、Insight Agent
