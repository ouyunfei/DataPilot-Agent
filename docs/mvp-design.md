# 基于 LangGraph 的智能数据分析 Agent 设计

## 1. 项目定位

本项目是一个面向业务数据查询和分析的 AI Agent 后端。用户不需要编写 SQL，只需要输入自然语言问题，系统即可自动理解业务数据表结构，调用 DeepSeek 生成 SQL，完成安全校验，执行查询，并返回 SQL 解释和中文分析结论。

当前阶段继续只做后端，不做前端、登录、复杂权限系统、多智能体和生产部署。

## 2. 核心能力

- 自然语言问题输入
- 三表 schema 获取和字段说明注入
- DeepSeek SQL 自动生成
- SQL 解释生成
- SQLGlot AST 安全校验
- SQLite 查询执行
- 语义层业务指标口径
- 可信 SQL 命中
- 查询日志
- 图表推荐
- Top 5 多行中文结果总结
- FastAPI 接口输出结构化结果

## 3. 模块划分

### API 层

位置：`app/api/routes.py`

职责：

- 提供 `POST /api/chat`
- 接收 `ChatRequest`
- 调用 `DataAnalysisAgent`
- 返回包含 `sql_explanation` 的 `ChatResponse`

### Agent 工作流层

位置：`app/agent/workflow.py`

职责：

- 使用 LangGraph `StateGraph` 编排节点
- 定义 `AnalysisState`
- 串联 schema、SQL、SQL 解释、校验、执行、分析等状态
- 在 SQL 不安全时跳过执行节点

### 数据库层

位置：`app/db/database.py`

职责：

- 自动创建 SQLite 数据库
- 初始化 `orders`、`users`、`products` 示例数据
- 输出三张表结构、字段说明和关联关系
- 执行只读查询并返回字典列表

### SQL 安全层

位置：`app/services/sql_validator.py`

职责：

- 使用 SQLGlot AST 校验 SQL
- 只允许单条 `SELECT`
- 禁止多语句 SQL
- 禁止注释
- 禁止写操作和 DDL 关键字
- 禁止 `SELECT *`
- 只允许访问 `orders`、`users`、`products`
- 自动追加或收敛 `LIMIT 100`

### LLM 层

位置：`app/services/llm.py`

职责：

- 定义 `BaseLLMClient` 协议
- 使用 `DeepSeekLLMClient` 调用 DeepSeek OpenAI-compatible Chat Completions API
- 通过 `.env` 读取 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL` 和 `DEEPSEEK_BASE_URL`
- SQL 生成阶段返回 `sql` 和 `sql_explanation`
- 分析阶段基于查询结果生成中文 Top 5 总结

## 4. LangGraph 工作流

```text
START
  -> retrieve_schema
  -> generate_sql
  -> validate_sql
  -> execute_sql 或 analyze_result
  -> analyze_result
  -> END
```

关键设计点：

- `generate_sql` 调用 DeepSeek，生成 SQL 和 SQL 解释
- `validate_sql` 是执行数据库前的强制节点
- 如果校验失败，状态中写入 `error`
- 条件边根据 `error` 决定是否跳过 `execute_sql`
- `analyze_result` 统一负责最终中文回答，错误场景返回空回答
- `run` 结束后写入查询日志，记录问题、SQL、命中情况、图表类型、行数、错误和耗时

## 5. 语义层与可信答案

位置：`app/services/semantic.py`

当前语义层包含：

- 销售额
- 退款率
- 客单价
- 毛利
- 订单数

可信答案用于高频问题，命中后跳过 DeepSeek SQL 生成，但仍经过 SQL 安全校验和数据库执行。

## 6. 数据库设计

当前 SQLite 示例库包含：

- `users`：用户维度表
- `products`：商品维度表
- `orders`：订单事实表

表关系：

- `orders.user_id = users.id`
- `orders.product_id = products.id`

`orders` 保留 `product_name`、`category`、`city` 冗余字段，便于同时展示简单聚合查询和三表 JOIN 查询。

## 7. 安全策略

当前采用字符串预检加 SQLGlot AST 校验：

- SQL 去除首尾空白后必须以 `SELECT` 开头
- 只允许末尾有一个分号
- 不允许 `--`、`/* */` 注释
- 不允许写操作和 DDL 关键字
- AST 根节点必须是 `SELECT`
- 不允许 `SELECT *`
- 只能访问白名单表
- 没有 `LIMIT` 时自动追加 `LIMIT 100`
- `LIMIT` 超过 100 时收敛为 100
- 校验失败时直接返回错误，不执行 SQL

后续可以继续加入字段白名单、查询超时、成本估算和更细粒度的数据权限。

## 8. 图表推荐与日志

接口新增 `chart` 和 `trusted_answer` 字段。

图表推荐规则：

- 日期趋势推荐折线图
- 排行或对比推荐柱状图
- 无数据或字段不明确推荐表格

查询日志写入 SQLite `query_logs` 表，便于后续统计高频问题、失败问题和慢查询。

## 9. 示例业务问题覆盖

- 最近 30 天销售额最高的 5 个商品是什么？
- 哪个商品品类的退款率最高？
- 最近一个月每天的销售额趋势如何？
- 不同城市的订单金额排名如何？
- 哪些用户的消费金额最高？
- 哪个用户等级的客单价最高？
- 哪个品牌的销售额最高？
- 哪个城市购买家用电器的金额最高？

## 10. 面试展示亮点

- 不是普通 ChatBot，而是可解释的数据分析 Agent 工作流
- LangGraph 明确拆分 Agent 节点，便于展示状态流转和扩展能力
- DeepSeek 负责生成 SQL、解释 SQL 和总结结果
- 可信 SQL 和语义层降低大模型随机性
- 查询日志体现可运营能力
- 图表推荐为后续前端可视化预留接口
- SQL 执行前有 SQLGlot AST 安全校验，体现后端风险意识
- LLM、数据库、API、校验逻辑分层清晰，适合后续替换和扩展
- SQLite 自动初始化，项目 clone 后可直接运行
- 测试覆盖关键路径，能够证明接口可用且危险 SQL 会被拦截

## 11. 后续路线

1. 扩展数据库适配层，支持 MySQL 和 PostgreSQL。
2. 使用 Qdrant 存储字段口径、指标定义和业务知识。
3. 使用 Redis 缓存 schema、热门查询和会话状态。
4. 使用 Celery 支持异步长查询和定时报表。
5. 拆分多智能体：Schema Agent、SQL Agent、SQL Review Agent、Insight Agent。
6. Docker 化并补充 CI 流程。
