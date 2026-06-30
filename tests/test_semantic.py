from app.services.semantic import build_semantic_context, find_trusted_answer, recommend_chart


def test_semantic_context_contains_business_metrics():
    context = build_semantic_context()

    assert "销售额" in context
    assert "退款率" in context
    assert "客单价" in context


def test_find_trusted_answer_matches_known_question():
    answer = find_trusted_answer("最近 30 天销售额最高的 5 个商品是什么？")

    assert answer is not None
    assert answer["sql"].upper().startswith("SELECT")
    assert "LIMIT 5" in answer["sql"].upper()


def test_recommend_chart_for_ranking_and_trend():
    ranking = recommend_chart([{"product_name": "人体工学椅", "total_amount": 100}])
    trend = recommend_chart([{"order_date": "2026-06-01", "total_amount": 100}])

    assert ranking["type"] == "bar"
    assert trend["type"] == "line"
