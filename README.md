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
│   │   └── sql_validator.py     # SQLGlot 安全校验
│   └── main.py                  # FastAPI 应用入口
├── docs/
│   ├── mvp-design.md
│   └── superpowers/
├── tests/
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
- `analyze_result`：调用 DeepSeek，基于查询结果生成中文业务分析结论

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

## 接口示例

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
  "sql": "SELECT product_name, ROUND(SUM(amount), 2) AS total_amount, COUNT(*) AS order_count FROM orders WHERE status = 'paid' GROUP BY product_name ORDER BY total_amount DESC LIMIT 5",
  "sql_explanation": "按商品名称分组，统计已支付订单销售额，并按销售额倒序取前 5 名。",
  "data": [
    {
      "product_name": "人体工学椅",
      "total_amount": 13311.55,
      "order_count": 8
    }
  ],
  "answer": "最近 30 天销售额最高的 Top 5 商品分别是人体工学椅、咖啡机、冲锋衣、空气炸锅和智能电饭煲，其中人体工学椅排名第一。",
  "error": null
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

## SQL 安全策略

SQL 执行前必须通过 `validate_sql`：

- 只允许单条 `SELECT`
- 禁止 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`TRUNCATE`
- 禁止注释和多语句
- 禁止 `SELECT *`
- 只允许访问白名单表：`orders`、`users`、`products`
- 没有 `LIMIT` 时自动追加 `LIMIT 100`
- `LIMIT` 超过 100 时自动收敛为 `LIMIT 100`
- 使用 SQLGlot 做 AST 级别校验

## 运行测试

```bash
python -m pytest -q
```

## 后续扩展方向

- 支持多数据库：将 `SQLiteDatabase` 抽象为通用数据库接口，扩展 MySQL/PostgreSQL
- 加入 Qdrant：存储业务指标解释、字段口径和历史查询样例，增强 schema 理解
- 加入 Redis：缓存 schema、热门查询结果和会话上下文
- 加入 Celery：处理耗时查询、异步报表和定时分析任务
- 多智能体拆分：Schema Agent、SQL Agent、SQL Review Agent、Insight Agent
- Docker 化：提供统一开发和部署环境
