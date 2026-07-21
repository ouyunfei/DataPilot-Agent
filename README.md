# DataPilot Agent

面向业务数据分析的 **自然语言问数后端 Agent**。

用户输入中文问题，系统自动理解数据表、生成安全 SQL、查询 MySQL，并返回结构化数据、中文结论、图表建议和规则洞察。

## 核心亮点

- **Text-to-SQL Agent**：LangGraph 编排 `schema -> knowledge -> SQL -> validate -> execute -> analyze`。
- **默认 MySQL**：`orders / users / products` 示例业务库和平台元数据库默认落 MySQL。
- **SQL 安全防护**：SQLGlot AST 校验，只允许单条 `SELECT`，强制 `LIMIT 100`，表/字段白名单控制。
- **语义层 + 可信答案**：指标口径可配置，高频问题可优先命中可信 SQL。
- **Local RAG**：Qdrant Local + `BAAI/bge-small-zh-v1.5` 召回 Schema、指标、可信 SQL、优质历史问答。
- **工程闭环**：FastAPI、Docker Compose、pytest、离线 eval、GitHub Actions CI。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| API | FastAPI / Pydantic |
| Agent | LangGraph |
| LLM | DeepSeek |
| 数据库 | MySQL 默认，PostgreSQL 可选 |
| SQL 安全 | SQLGlot |
| RAG | Qdrant Local / sentence-transformers |
| 测试 | pytest / deterministic evals |

## 快速启动

### Docker 推荐

```bash
copy .env.example .env
```

如需真实调用 DeepSeek，填写 `.env` 中的 `DEEPSEEK_API_KEY`，然后启动：

```bash
docker compose up --build
```

访问：

- API Health: <http://127.0.0.1:8000/health>
- Swagger: <http://127.0.0.1:8000/docs>

Docker 会启动后端和 MySQL，并初始化示例表、平台表、默认指标和默认数据源。

### 本地开发

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

本地直连 Docker MySQL 时默认端口是 `3307`：

```bash
docker compose up -d mysql
```

## 关键配置

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-v4-flash
META_DATABASE_URL=mysql://root:datapilot_root123@127.0.0.1:3307/datapilot
DEFAULT_MYSQL_DATA_SOURCE_URL=mysql://datapilot_ro:datapilot123@127.0.0.1:3307/datapilot
QDRANT_PATH=data/qdrant
QDRANT_COLLECTION=datapilot_knowledge_bge_small_zh_v15
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
KNOWLEDGE_TOP_K=5
QUERY_TIMEOUT_SECONDS=5
```

`.env` 不要提交到仓库。

## 接口示例

自然语言问数：

```bash
curl -X POST "http://127.0.0.1:8000/api/chat" ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"最近 30 天销售额最高的 5 个商品是什么？\"}"
```

响应会包含：

```json
{
  "sql": "SELECT ... LIMIT 5",
  "data": [],
  "chart": { "type": "bar" },
  "insights": [],
  "knowledge_sources": [],
  "answer": "中文业务分析结论",
  "error": null
}
```

常用接口：

| 接口 | 说明 |
| --- | --- |
| `POST /api/chat` | 自然语言问数 |
| `GET /api/query-logs` | 查询日志 |
| `GET /api/query-stats` | 查询统计 |
| `GET /api/data-sources` | 数据源管理 |
| `GET /api/catalog/tables` | 数据目录 |
| `GET /api/metrics` | 指标管理 |
| `GET /api/security/policies` | SQL 安全策略 |

## 安全策略

所有生成 SQL 在执行前都会经过统一校验：

- 只允许单条 `SELECT`
- 禁止 DDL / DML / 多语句 / 注释
- 禁止 `SELECT *`
- 只允许访问当前数据源白名单表和字段
- 自动追加或收敛到 `LIMIT 100`
- 查询执行超时保护

## Local RAG

重建本地知识索引：

```bash
python scripts/rebuild_knowledge_index.py
```

知识库不可用、模型未下载、无召回或 Qdrant 异常时，系统会 fail-open 回到原始 Text-to-SQL 流程；SQL 安全规则始终生效。

## 验证

```bash
python -m pytest -q
python scripts/run_evals.py
```

当前 eval 使用 fake LLM 和 MySQL 默认数据源，不依赖真实 DeepSeek 或已构建的 Qdrant Collection。

## 项目结构

```text
app/
  api/        FastAPI 路由
  agent/      LangGraph 工作流
  db/         MySQL / PostgreSQL 数据源与平台元数据库
  services/   LLM、SQL 校验、语义层、RAG、洞察
  schemas/    Pydantic 模型
docker/       MySQL / PostgreSQL 初始化脚本
evals/        Text-to-SQL 评测集
scripts/      eval 与知识索引脚本
tests/        单元测试和 API 测试
docs/         设计文档
```

## 进一步阅读

- [MVP 设计](docs/mvp-design.md)
- [Local RAG 需求](docs/qdrant-local-rag-requirements.md)
- [存储架构路线图](docs/storage-architecture-roadmap.md)
