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
- 数据源配置管理
- 数据源级表权限白名单
- 数据源级字段权限白名单
- 数据目录接口
- SQLite 查询执行
- PostgreSQL 查询执行
- MySQL 查询执行
- 指标管理和语义层业务口径配置
- 可信 SQL 命中
- 查询日志
- 多轮追问会话上下文
- 查询统计接口
- 图表推荐
- 异常 / 趋势发现
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
- 支持传入 `session_id` 进行多轮追问
- 支持传入 `data_source_id` 指定数据源
- 提供 `GET /api/data-sources`、`POST /api/data-sources`、`PUT /api/data-sources/{id}`、`DELETE /api/data-sources/{id}`、`POST /api/data-sources/{id}/test`
- 提供 `GET /api/catalog/tables`、`GET /api/catalog/tables/{table_name}/columns`
- 提供 `GET /api/metrics`、`POST /api/metrics`、`PUT /api/metrics/{id}`、`DELETE /api/metrics/{id}`
- 提供 `GET /api/query-stats` 查询运营统计指标

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
- 保存 `data_sources` 数据源配置
- 为每个数据源维护独立表白名单
- 为每个数据源维护独立字段白名单
- 提供数据目录元数据：表名、字段名、字段类型、字段说明和可查询状态
- 支持 PostgreSQL / MySQL 连接测试、schema 读取和 SELECT 查询执行
- 保存 `metrics` 指标配置
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
- 只允许访问当前数据源配置的白名单表
- 只允许访问当前数据源配置的白名单字段
- 自动追加或收敛 `LIMIT 100`
- SQLite 查询执行超时保护，默认 `QUERY_TIMEOUT_SECONDS=5`
- PostgreSQL / MySQL 查询执行超时保护

### 洞察层

位置：`app/services/insights.py`

职责：

- 根据查询结果生成确定性 `insights`
- 识别日期趋势最高值
- 识别相邻日期明显下降
- 识别品类退款率异常偏高
- 识别 Top 1 和 Top 2 差距是否明显

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
- `run` 会创建或复用 `session_id`，把最近会话上下文注入 schema prompt
- `run` 会解析 `data_source_id`，把对应数据源的表和字段白名单用于 schema 注入、SQL 校验和查询执行
- 当数据源为 PostgreSQL 或 MySQL 时，Agent 会动态读取对应数据库 schema，并使用相应 SQL 方言执行查询
- `execute_sql` 查询成功后会生成 `insights`，`analyze_result` 会把洞察短句追加进最终回答

## 5. 语义层与可信答案

位置：`app/services/semantic.py`

当前语义层指标存储在 SQLite `metrics` 表中，默认包含：

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

新增 `data_sources` 数据源配置表：

| 字段 | 说明 |
| --- | --- |
| `id` | 数据源 ID |
| `name` | 数据源名称 |
| `db_type` | `sqlite`、`mysql` 或 `postgresql` |
| `database_url` | 数据库连接地址 |
| `allowed_tables` | 允许查询的表名 JSON |
| `allowed_columns` | 允许查询的字段名 JSON |
| `is_default` | 是否默认数据源 |
| `created_at` | 创建时间 |

启动时自动初始化默认数据源 `default_sqlite`，白名单表为 `orders`、`users`、`products`。SQLite、PostgreSQL 和 MySQL 均支持真实连接测试、数据目录读取和只读查询；MySQL 数据源必须显式配置字段白名单。

Docker 提供 MySQL 示例库，首次启动自动创建三张业务表并初始化 80 个用户、30 个商品和 1000 个订单。真实 MySQL 数据源不会自动建表或写入数据，推荐使用只有 `SELECT` 权限的账号。数据源接口返回连接地址时会隐藏密码。

数据源支持更新连接地址、表/字段白名单和默认状态，并允许删除非默认数据源。默认数据源的切换在同一事务中完成；当前默认数据源不能直接取消默认状态或删除，避免系统失去可用的默认数据源。

新增 `metrics` 指标配置表：

| 字段 | 说明 |
| --- | --- |
| `id` | 指标 ID |
| `metric_key` | 指标唯一标识 |
| `name` | 指标中文名 |
| `expression` | 指标计算口径 |
| `description` | 业务说明 |
| `enabled` | 是否启用 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

## 7. 安全策略

当前采用字符串预检加 SQLGlot AST 校验：

- SQL 去除首尾空白后必须以 `SELECT` 开头
- 只允许末尾有一个分号
- 不允许 `--`、`/* */` 注释
- 不允许写操作和 DDL 关键字
- AST 根节点必须是 `SELECT`
- 不允许 `SELECT *`
- 只能访问白名单表
- 白名单表来自当前数据源，而不是写死在代码中
- 只能访问白名单字段
- 字段白名单来自当前数据源，schema 注入和 SQL 校验共用同一份配置
- 没有 `LIMIT` 时自动追加 `LIMIT 100`
- `LIMIT` 超过 100 时收敛为 100
- SQLite 执行阶段有超时保护
- PostgreSQL 执行阶段通过 `statement_timeout` 做超时保护
- MySQL 执行阶段通过驱动超时和 `MAX_EXECUTION_TIME` 做超时保护
- 校验失败时直接返回错误，不执行 SQL

后续可以继续加入成本估算、行级权限和更细粒度的数据权限。

## 8. 图表推荐、洞察与日志

接口新增 `chart`、`insights` 和 `trusted_answer` 字段。

图表推荐规则：

- 日期趋势推荐折线图
- 排行或对比推荐柱状图
- 无数据或字段不明确推荐表格

洞察规则：

- 日期字段 + 数值字段：识别最高日期
- 相邻日期数值下降超过 30%：提示明显波动
- `category` + `refund_rate`：识别明显高于平均水平的品类
- 排行结果：比较 Top 1 和 Top 2 差距，超过 20% 判定明显

这些洞察由规则生成，不依赖 LLM 猜测，避免编造不存在的数据。

查询日志写入 SQLite `query_logs` 表，便于后续统计高频问题、失败问题和慢查询。

错误会记录 `error_code`，包括 `llm_error`、`sql_safety_error`、`execution_error`、`data_source_error` 和 `query_timeout`。

多轮追问使用 `chat_sessions` 和 `chat_messages` 表保存最近问答。用户第一次请求不需要传 `session_id`，后端会自动生成；后续追问带上同一个 `session_id`，Agent 会把最近 3 条上下文交给 SQL 生成节点。

查询统计接口 `GET /api/query-stats` 基于 `query_logs` 聚合：

- 总查询数、成功查询数、失败查询数
- 可信答案命中数
- 平均耗时
- 图表类型分布
- 用户反馈分布
- Top 5 高频问题

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
- 可信 SQL 和可配置语义层降低大模型随机性
- 查询日志体现可运营能力
- 多轮追问体现 Agent 上下文理解能力
- 查询统计接口体现运营监控和效果分析能力
- 数据源管理和动态表白名单体现企业级数据治理能力
- 数据目录、字段白名单和查询保护体现企业级安全治理能力
- PostgreSQL / MySQL 真实数据源接入体现平台可连接真实数据库
- 指标管理体现企业指标口径治理能力
- 图表推荐为后续前端可视化预留接口
- 异常 / 趋势发现让结果解释从“总结数据”升级为“发现问题”
- SQL 执行前有 SQLGlot AST 安全校验，体现后端风险意识
- LLM、数据库、API、校验逻辑分层清晰，适合后续替换和扩展
- SQLite 自动初始化，项目 clone 后可直接运行
- 测试覆盖关键路径，能够证明接口可用且危险 SQL 会被拦截

## 11. 后续路线

1. 使用 Qdrant 存储字段口径、指标定义和业务知识。
2. 使用 Redis 缓存 schema、热门查询和会话状态。
3. 使用 Celery 支持异步长查询和定时报表。
4. 拆分多智能体：Schema Agent、SQL Agent、SQL Review Agent、Insight Agent。
5. 增加异常趋势发现、图表配置和更完整的统计看板接口。
