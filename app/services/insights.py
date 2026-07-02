from __future__ import annotations

from typing import Any


def recommend_insights(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not rows:
        return []

    insights: list[dict[str, str]] = []
    keys = list(rows[0].keys())
    date_key = _first_key(keys, ("date", "created_at"))
    value_key = _first_key(keys, ("amount", "sales", "count", "rate"))

    if date_key and value_key:
        insights.extend(_trend_insights(rows, date_key, value_key))

    if "category" in keys and "refund_rate" in keys:
        insight = _refund_rate_outlier(rows)
        if insight:
            insights.append(insight)

    if not date_key and value_key and len(rows) >= 2:
        insights.append(_top_gap_insight(rows, keys, value_key))

    return insights[:4]


def _trend_insights(
    rows: list[dict[str, Any]],
    date_key: str,
    value_key: str,
) -> list[dict[str, str]]:
    points = sorted(
        [(str(row[date_key]), _number(row.get(value_key))) for row in rows],
        key=lambda item: item[0],
    )
    points = [(date, value) for date, value in points if value is not None]
    if not points:
        return []

    peak_date, peak_value = max(points, key=lambda item: item[1])
    insights = [
        {
            "type": "peak",
            "message": f"{_metric_name(value_key)}最高日期是 {peak_date}，数值为 {_format_number(peak_value)}。",
        }
    ]

    drops = []
    for index in range(1, len(points)):
        prev_date, prev_value = points[index - 1]
        date, value = points[index]
        if prev_value <= 0 or value >= prev_value:
            continue
        drop_rate = (prev_value - value) / prev_value
        if drop_rate >= 0.3:
            drops.append((drop_rate, date, prev_date))

    if drops:
        drop_rate, date, prev_date = max(drops, key=lambda item: item[0])
        insights.append(
            {
                "type": "drop",
                "message": f"{date} 较 {prev_date} 下降 {_format_percent(drop_rate)}，存在明显波动。",
            }
        )
    return insights


def _refund_rate_outlier(rows: list[dict[str, Any]]) -> dict[str, str] | None:
    values = [
        (str(row["category"]), _number(row.get("refund_rate")))
        for row in rows
        if _number(row.get("refund_rate")) is not None
    ]
    if len(values) < 2:
        return None

    average = sum(value for _, value in values) / len(values)
    category, value = max(values, key=lambda item: item[1])
    if value >= average * 1.5 and value - average >= 0.05:
        return {
            "type": "outlier",
            "message": f"{category} 退款率为 {_format_percent(value)}，明显高于平均水平 {_format_percent(average)}。",
        }
    return None


def _top_gap_insight(
    rows: list[dict[str, Any]],
    keys: list[str],
    value_key: str,
) -> dict[str, str]:
    label_key = next((key for key in keys if key != value_key), keys[0])
    first = _number(rows[0].get(value_key)) or 0
    second = _number(rows[1].get(value_key)) or 0
    first_label = rows[0].get(label_key, "Top 1")
    second_label = rows[1].get(label_key, "Top 2")
    if second <= 0:
        return {"type": "gap", "message": f"{first_label} 暂列第一，暂无有效第二名可比较。"}

    gap = (first - second) / second
    level = "明显" if gap >= 0.2 else "不明显"
    return {
        "type": "gap",
        "message": f"Top 1 {first_label} 比 Top 2 {second_label} 高 {_format_percent(gap)}，头部差距{level}。",
    }


def _first_key(keys: list[str], needles: tuple[str, ...]) -> str:
    return next((key for key in keys if any(needle in key for needle in needles)), "")


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_name(key: str) -> str:
    if "amount" in key or "sales" in key:
        return "销售额"
    if "rate" in key:
        return "比例"
    if "count" in key:
        return "数量"
    return key


def _format_number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"
