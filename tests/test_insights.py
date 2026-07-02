from app.services.insights import recommend_insights


def test_recommend_insights_detects_daily_peak_and_drop():
    insights = recommend_insights(
        [
            {"order_date": "2026-06-01", "total_amount": 1000},
            {"order_date": "2026-06-02", "total_amount": 1800},
            {"order_date": "2026-06-03", "total_amount": 900},
        ]
    )

    assert any(item["type"] == "peak" and "2026-06-02" in item["message"] for item in insights)
    assert any(item["type"] == "drop" and "下降 50.0%" in item["message"] for item in insights)


def test_recommend_insights_detects_refund_rate_outlier():
    insights = recommend_insights(
        [
            {"category": "数码配件", "refund_rate": 0.05},
            {"category": "家用电器", "refund_rate": 0.28},
            {"category": "生活日用", "refund_rate": 0.04},
        ]
    )

    assert any(
        item["type"] == "outlier" and "家用电器" in item["message"] for item in insights
    )


def test_recommend_insights_detects_top_gap():
    insights = recommend_insights(
        [
            {"product_name": "人体工学椅", "total_amount": 12800},
            {"product_name": "咖啡机", "total_amount": 10000},
            {"product_name": "冲锋衣", "total_amount": 8800},
        ]
    )

    assert any(item["type"] == "gap" and "28.0%" in item["message"] for item in insights)
