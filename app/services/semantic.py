from __future__ import annotations

from typing import Any


METRICS = {
    "sales_amount": {
        "name": "销售额",
        "expression": "SUM(orders.amount)",
        "description": "已支付订单金额总和。",
    },
    "refund_rate": {
        "name": "退款率",
        "expression": "退款订单数 / 总订单数",
        "description": "refund_amount > 0 或 status = 'refunded' 的订单占比。",
    },
    "average_order_value": {
        "name": "客单价",
        "expression": "SUM(orders.amount) / COUNT(DISTINCT orders.id)",
        "description": "平均每笔订单金额。",
    },
    "gross_profit": {
        "name": "毛利",
        "expression": "SUM(orders.amount - products.cost_price)",
        "description": "订单金额减商品成本价后的金额。",
    },
    "order_count": {
        "name": "订单数",
        "expression": "COUNT(orders.id)",
        "description": "订单明细数量。",
    },
}


TRUSTED_ANSWERS = {
    "最近30天销售额最高的5个商品是什么": {
        "sql": """
        SELECT
            product_name,
            ROUND(SUM(amount), 2) AS total_amount,
            COUNT(*) AS order_count
        FROM orders
        WHERE status = 'paid'
          AND created_at >= date('now', '-30 days')
        GROUP BY product_name
        ORDER BY total_amount DESC
        LIMIT 5
        """,
        "sql_explanation": "使用可信 SQL：筛选最近 30 天已支付订单，按商品汇总销售额并取 Top 5。",
    },
    "哪个商品品类的退款率最高": {
        "sql": """
        SELECT
            category,
            COUNT(*) AS order_count,
            SUM(CASE WHEN refund_amount > 0 OR status = 'refunded' THEN 1 ELSE 0 END) AS refund_count,
            ROUND(SUM(CASE WHEN refund_amount > 0 OR status = 'refunded' THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS refund_rate
        FROM orders
        GROUP BY category
        ORDER BY refund_rate DESC, refund_count DESC
        LIMIT 5
        """,
        "sql_explanation": "使用可信 SQL：按品类统计退款订单占比，并按退款率倒序取 Top 5。",
    },
}


def build_semantic_context(allowed_tables: list[str] | None = None) -> str:
    allowed = set(allowed_tables or ["orders", "users", "products"])
    lines = ["业务语义层指标："]
    for metric in METRICS.values():
        expression = metric["expression"]
        if any(f"{table}." in expression for table in {"orders", "users", "products"} - allowed):
            continue
        lines.append(f"- {metric['name']}：{metric['description']}计算口径：{metric['expression']}")
    return "\n".join(lines)


def find_trusted_answer(question: str) -> dict[str, str] | None:
    answer = TRUSTED_ANSWERS.get(_normalize_question(question))
    if answer is None:
        return None
    return {**answer, "sql": answer["sql"].strip()}


def recommend_chart(rows: list[dict[str, Any]]) -> dict[str, str]:
    if not rows:
        return {"type": "table", "x": "", "y": "", "reason": "无数据时使用表格占位。"}

    keys = list(rows[0].keys())
    y_key = _first_key(keys, ("amount", "sales", "count", "rate"))
    x_key = next((key for key in keys if key != y_key), keys[0])

    if "date" in x_key:
        return {"type": "line", "x": x_key, "y": y_key, "reason": "日期趋势适合折线图。"}
    if y_key:
        return {"type": "bar", "x": x_key, "y": y_key, "reason": "排行或对比数据适合柱状图。"}
    return {"type": "table", "x": "", "y": "", "reason": "字段结构不明确时使用表格。"}


def _first_key(keys: list[str], needles: tuple[str, ...]) -> str:
    return next((key for key in keys if any(needle in key for needle in needles)), "")


def _normalize_question(question: str) -> str:
    return "".join(char for char in question if char.isalnum())
