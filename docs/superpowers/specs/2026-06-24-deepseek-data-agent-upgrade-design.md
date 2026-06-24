# DeepSeek 数据分析 Agent 升级设计

## 背景

当前 DataPilot Agent 已完成后端 MVP：FastAPI 接收自然语言问题，LangGraph 编排 schema 获取、SQL 生成、安全校验、SQL 执行和中文总结，SQLite 中已有 `orders` 示例表。当前 LLM 为 Mock，数据库结构较简单，SQL 安全校验以字符串扫描为主，响应中没有 SQL 解释字段，分析结论只总结第一名。

本次升级目标是让项目更接近真实业务数据分析 Agent，并增强秋招展示价值。

## 用户确认的关键决策

- LLM 默认直接使用 DeepSeek。
- 暂时不需要 Mock 运行路径。
- API key 不写入源码和文档示例中的真实值，通过 `.env` 或环境变量读取。
- 继续只做后端，不做前端。

## 目标能力

1. 默认接入 DeepSeek 生成 SQL、SQL 解释和分析结论。
2. SQLite 示例库扩展为 `orders`、`users`、`products` 三张表。
3. `answer` 支持 Top 5、多行业务总结，而不是只总结第一名。
4. 使用 `sqlglot` 做 AST 级 SQL 安全校验。
5. 响应新增 `sql_explanation` 字段。
6. README 和设计文档同步更新。

## 数据库设计

### users

用户维度表：

- `id`：用户 ID，主键
- `name`：用户姓名
- `city`：常驻城市
- `level`：用户等级，例如 普通、银卡、金卡、黑金
- `registered_at`：注册日期

### products

商品维度表：

- `id`：商品 ID，主键
- `product_name`：商品名称
- `category`：商品品类
- `brand`：品牌
- `cost_price`：成本价
- `list_price`：标价

### orders

订单事实表：

- `id`：订单 ID，主键
- `user_id`：用户 ID，关联 `users.id`
- `product_id`：商品 ID，关联 `products.id`
- `product_name`：商品名称冗余字段，便于展示和简单查询
- `category`：商品品类冗余字段
- `city`：订单城市
- `amount`：订单金额
- `status`：订单状态
- `created_at`：下单日期
- `refund_amount`：退款金额

保留 `product_name`、`category`、`city` 冗余字段，是为了让基础 SQL 和三表 JOIN 查询都能展示，降低学习成本。

## LLM 设计

新增 `DeepSeekLLMClient`：

- 使用 DeepSeek OpenAI-compatible Chat Completions API。
- 默认模型：`deepseek-v4-flash`。
- 通过环境变量读取：
  - `DEEPSEEK_API_KEY`
  - `DEEPSEEK_MODEL`
  - `DEEPSEEK_BASE_URL`
- LLM 输出结构化 JSON：
  - `sql`
  - `sql_explanation`

SQL 生成 prompt 要求：

- 只生成 SQLite 方言 SQL。
- 只允许 `SELECT`。
- 必须包含 `LIMIT`。
- 禁止 `SELECT *`。
- 只能使用 `orders`、`users`、`products`。
- 优先使用清晰别名。
- 对金额使用 `ROUND(..., 2)`。
- 返回 JSON，不返回 Markdown 代码块。

分析 prompt 要求：

- 用中文回答。
- 对排行类结果总结 Top 5。
- 包含关键数值、排序和简短业务洞察。
- 无数据时说明未查询到符合条件的数据。

## LangGraph 工作流设计

保持五个主要节点，并扩展状态：

```text
retrieve_schema
  -> generate_sql
  -> validate_sql
  -> execute_sql
  -> analyze_result
```

`AnalysisState` 新增：

- `sql_explanation`

节点变化：

- `generate_sql`：DeepSeek 返回 SQL 和 SQL 解释。
- `validate_sql`：返回校验后的 SQL。必要时自动补 `LIMIT 100`。
- `analyze_result`：DeepSeek 基于问题、SQL、SQL 解释和结果生成中文总结。

如果 SQL 校验失败，跳过执行，直接返回错误。

## SQL 安全设计

新增依赖：`sqlglot`。

安全策略：

- 只允许单条 SQL。
- AST 根节点必须是 `SELECT`。
- 禁止 `SELECT *`。
- 只允许白名单表：
  - `orders`
  - `users`
  - `products`
- 禁止写操作和 DDL 关键字：
  - `INSERT`
  - `UPDATE`
  - `DELETE`
  - `DROP`
  - `ALTER`
  - `TRUNCATE`
  - `CREATE`
  - `REPLACE`
  - `ATTACH`
  - `DETACH`
  - `PRAGMA`
  - `VACUUM`
  - `REINDEX`
- 不允许注释。
- 不允许多语句。
- 强制 LIMIT：
  - 没有 `LIMIT` 时自动追加 `LIMIT 100`
  - 超过 `100` 时改写为 `LIMIT 100`

这样既能保证可用性，也能控制查询返回规模。

## API 响应变化

`POST /api/chat` 响应新增字段：

```json
{
  "question": "最近 30 天销售额最高的 5 个商品是什么？",
  "sql": "SELECT ... LIMIT 5",
  "sql_explanation": "按商品名称分组，统计最近 30 天已支付订单的销售额，并按销售额倒序取前 5 名。",
  "data": [],
  "answer": "最近 30 天销售额最高的 Top 5 商品分别是...",
  "error": null
}
```

## 测试策略

更新并新增测试：

- 数据库初始化后存在 `orders`、`users`、`products`。
- schema 描述包含三张表和关键字段。
- SQL 校验拒绝危险语句。
- SQL 校验拒绝 `SELECT *`。
- SQL 校验拒绝非白名单表。
- SQL 校验自动追加或收敛 `LIMIT`。
- API 响应包含 `sql_explanation`。
- API 危险 SQL 场景仍不会执行查询。

由于默认 DeepSeek 会依赖外部网络和 API key，测试中应使用注入式 fake LLM，避免单元测试依赖真实 DeepSeek 服务。

## 文档更新

更新：

- `README.md`
- `docs/mvp-design.md`

新增说明：

- `.env` 配置方式
- DeepSeek 启动方式
- 三表 schema
- `sql_explanation` 字段
- SQL 安全策略
- Postman 测试示例

## 风险与处理

- DeepSeek API key 缺失：应用启动时给出清晰错误，提示配置 `DEEPSEEK_API_KEY`。
- DeepSeek 返回非 JSON：做 JSON 提取和异常提示。
- DeepSeek 生成不安全 SQL：由 `validate_sql` 拦截，绝不执行。
- DeepSeek 生成无 LIMIT SQL：自动追加 `LIMIT 100`。
- 当前已有 `data/datapilot.db` 旧库：初始化逻辑会补建新表；如旧 `orders` schema 不含 `product_id`，需要重建示例表或提供重置策略。

## 交付标准

- 本地服务可启动。
- `.env` 中配置 DeepSeek key 后，`POST /api/chat` 可真实调用 DeepSeek。
- SQLite 自动初始化三张表示例数据。
- 响应包含 `sql_explanation`。
- Top 5 问题返回多项总结。
- 不安全 SQL 被拦截。
- 全量测试通过。
