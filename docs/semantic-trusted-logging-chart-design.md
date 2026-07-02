# 语义层、可信答案、查询日志与图表推荐设计

## 目标

在现有自然语言问数链路上补齐四个后端能力：

- 语义层：沉淀销售额、退款率、客单价、毛利、订单数等业务指标口径。
- 可信答案：常见问题优先使用已验证 SQL，减少大模型随机性。
- 查询日志：记录问题、SQL、是否命中可信答案、图表类型、返回行数、错误和耗时。
- 图表推荐：根据查询结果字段推荐柱状图、折线图或表格。
- 异常 / 趋势洞察：根据查询结果用规则识别峰值、明显下降、退款率异常和 Top 差距。

## 实现方式

遵循最小后端实现，不引入新依赖。

### 语义层

位置：`app/services/semantic.py`

使用 Python 字典维护指标口径：

- 销售额：已支付订单金额总和
- 退款率：退款订单数 / 总订单数
- 客单价：销售额 / 订单数
- 毛利：订单金额 - 商品成本
- 订单数：订单明细数量

`build_semantic_context()` 会把这些指标拼接进 schema 上下文，让 DeepSeek 生成 SQL 时能看到统一业务口径。

### 可信答案

位置：`app/services/semantic.py`

当前内置两类高频可信 SQL：

- 最近 30 天销售额最高的 5 个商品是什么？
- 哪个商品品类的退款率最高？

命中可信答案时，`generate_sql` 节点跳过 DeepSeek SQL 生成，直接使用已验证 SQL。后续仍会执行 SQL 安全校验，保证可信 SQL 也不绕过安全层。

### 查询日志

位置：`app/db/database.py`

新增 `query_logs` 表：

| 字段 | 说明 |
| --- | --- |
| `question` | 用户问题 |
| `sql` | 最终执行 SQL |
| `trusted_answer` | 是否命中可信答案 |
| `chart_type` | 推荐图表类型 |
| `row_count` | 返回行数 |
| `error` | 错误信息 |
| `duration_ms` | 本次处理耗时 |
| `created_at` | 创建时间 |

日志在 `DataAnalysisAgent.run()` 结束时统一写入。

### 图表推荐

位置：`app/services/semantic.py`

最小规则：

- 有日期字段：推荐 `line`
- 有金额、数量、比例字段：推荐 `bar`
- 无数据或字段不明确：推荐 `table`

接口返回：

```json
{
  "chart": {
    "type": "bar",
    "x": "product_name",
    "y": "total_amount",
    "reason": "排行或对比数据适合柱状图。"
  }
}
```

### 异常 / 趋势洞察

位置：`app/services/insights.py`

使用确定性规则生成 `insights`，不依赖 LLM 猜测：

- 日期趋势：识别最高日期。
- 日期趋势：相邻日期下降超过 30% 时提示明显波动。
- 退款率：品类退款率明显高于平均水平时提示异常。
- 排行结果：比较 Top 1 和 Top 2 差距，超过 20% 判定明显。

## API 变化

`POST /api/chat` 新增字段：

- `trusted_answer`
- `chart`
- `insights`

示例：

```json
{
  "question": "最近 30 天销售额最高的 5 个商品是什么？",
  "trusted_answer": true,
  "chart": {
    "type": "bar",
    "x": "product_name",
    "y": "total_amount",
    "reason": "排行或对比数据适合柱状图。"
  }
}
```

## 后续扩展

- 语义层可迁移到 YAML 或数据库。
- 可信答案可增加命中统计和人工审核流程。
- 查询日志可增加用户反馈字段。
- 图表推荐可扩展为 ECharts 配置，但当前阶段只返回后端推荐，不开发前端。
