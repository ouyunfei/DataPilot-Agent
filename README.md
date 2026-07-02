# DataPilot Agent

基于 LangGraph 的智能数据分析 Agent。用户用自然语言提出业务数据问题，系统自动完成表结构理解、DeepSeek SQL 生成、SQL 安全校验、SQL 执行和中文分析总结。

这个项目不是普通聊天机器人，而是面向业务数据查询和分析场景的后端 Agent。当前版本默认接入 DeepSeek，SQLite 示例库包含 `orders`、`users`、`products` 三张表，并使用 SQLGlot 做 AST 级 SQL 安全校验。

## 功能特性

- FastAPI 后端服务
- LangGraph 编排数据分析工作流
- DeepSeek 生成 SQL、SQL 解释和中文分析结论
- SQLite 自动初始化订单、用户、商品三张示例表
- SQLGlot AST 安全校验
- 强制 `LIMIT`，最大返回 100 行
- 禁止 `SELECT *` 和非白名单表访问
- 数据源管理：支持 SQLite / MySQL / PostgreSQL 配置登记
- 表权限白名单：每个数据源独立配置允许查询的表
- 语义层沉淀销售额、退款率、客单价等业务指标口径
- 高频问题优先命中可信 SQL
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
- eval 评测集验证 Text-to-SQL 工作流质量
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
│   │   └── database.py          # SQLite 初始化、schema 获取、查询执行
│   ├── schemas/
│   │   └── chat.py              # Pydantic 请求/响应模型
│   ├── services/
│   │   ├── llm.py               # DeepSeek LLM 客户端
│   │   ├── semantic.py          # 语义层、可信答案和图表推荐
│   │   ├── insights.py          # 异常 / 趋势洞察规则
│   │   └── sql_validator.py     # SQLGlot 安全校验
│   └── main.py                  # FastAPI 应用入口
├── docs/
│   ├── mvp-design.md
│   └── superpowers/
├── evals/
│   └── questions.json          # Text-to-SQL 评测问题集
├── scripts/
│   └── run_evals.py            # eval 执行脚本
├── tests/
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

## 工作流设计

```text
retrieve_schema -> generate_sql -> validate_sql -> execute_sql -> analyze_result
```

节点职责：

- `retrieve_schema`：读取三张表结构、字段说明和表关系
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
```

启动服务：

```bash
uvicorn app.main:app --reload
```

默认访问：

- 健康检查：http://127.0.0.1:8000/health
- Swagger 文档：http://127.0.0.1:8000/docs

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
  "trusted_answer": true,
  "answer": "最近 30 天销售额最高的 Top 5 商品分别是人体工学椅、咖啡机、冲锋衣、空气炸锅和智能电饭煲，其中人体工学椅排名第一。Top 1 人体工学椅 比 Top 2 咖啡机 高 28.0%，头部差距明显。",
  "error": null
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

返回当前 SQL 安全策略，例如只允许 `SELECT`、禁止多语句、禁止 `SELECT *`、白名单表和最大 `LIMIT`。

### 数据源管理

```bash
curl "http://127.0.0.1:8000/api/data-sources"
```

创建数据源：

```bash
curl -X POST "http://127.0.0.1:8000/api/data-sources" ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"orders_only\",\"db_type\":\"sqlite\",\"database_url\":\"data/datapilot.db\",\"allowed_tables\":[\"orders\"]}"
```

测试数据源：

```bash
curl -X POST "http://127.0.0.1:8000/api/data-sources/1/test"
```

当前阶段 SQLite 数据源会真实检查数据库文件和白名单表；MySQL/PostgreSQL 先支持配置登记，真实连接执行留到下一阶段接入驱动。

## SQL 安全策略

SQL 执行前必须通过 `validate_sql`：

- 只允许单条 `SELECT`
- 禁止 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`TRUNCATE`
- 禁止注释和多语句
- 禁止 `SELECT *`
- 只允许访问当前数据源配置的白名单表
- 没有 `LIMIT` 时自动追加 `LIMIT 100`
- `LIMIT` 超过 100 时自动收敛为 `LIMIT 100`
- 使用 SQLGlot 做 AST 级别校验

## 语义层、可信答案、查询日志、图表推荐和洞察

新增能力沉淀在：

```text
docs/semantic-trusted-logging-chart-design.md
```

后端会把业务指标口径注入给 DeepSeek；常见问题命中可信 SQL；每次查询写入 `query_logs`；接口返回 `chart` 字段给未来前端使用。数据源白名单会同时作用于 schema 注入和 SQL 安全校验。

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

脚本使用临时 SQLite 和 fake LLM，不依赖真实 DeepSeek API key。它会检查 SQL 是否生成、安全校验是否通过、返回字段是否符合预期、图表类型是否正确。

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

讲解链路：LangGraph 获取 schema 和语义层，优先命中可信 SQL，经过 SQLGlot 安全校验后执行 SQLite 查询，再生成中文 Top 5 总结、规则洞察和图表推荐。

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
POST http://127.0.0.1:8000/api/query-logs/{id}/feedback
GET http://127.0.0.1:8000/api/security/policies
```

讲解查询日志和统计接口用于观察高频问题、失败问题、慢查询和图表使用分布，数据源白名单用于限制可查询表，用户反馈用于沉淀可信答案和优化语义层。

6. 演示工程化能力：

```text
docker compose up --build
python -m pytest -q
python scripts/run_evals.py
```

讲解 Docker 解决环境一致性，GitHub Actions 保证提交后自动测试，eval 评测集让 Agent 的 Text-to-SQL 能力可量化，而不是只靠手工试几个问题。

## 后续扩展方向

- 接入真实 MySQL/PostgreSQL 驱动，让已登记的数据源可以真实执行查询
- 加入 Qdrant：存储业务指标解释、字段口径和历史查询样例，增强 schema 理解
- 加入 Redis：缓存 schema、热门查询结果和会话上下文
- 加入 Celery：处理耗时查询、异步报表和定时分析任务
- 多智能体拆分：Schema Agent、SQL Agent、SQL Review Agent、Insight Agent
- Docker 化：提供统一开发和部署环境
