from app.db.database import SQLiteDatabase


def test_database_initializes_three_tables_and_returns_join_rows(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()

    schema = db.get_schema_description()
    rows = db.execute_select(
        """
        SELECT
            u.name AS user_name,
            p.product_name,
            SUM(o.amount) AS total_amount
        FROM orders o
        JOIN users u ON o.user_id = u.id
        JOIN products p ON o.product_id = p.id
        GROUP BY u.name, p.product_name
        ORDER BY total_amount DESC
        LIMIT 3
        """
    )

    assert "orders" in schema
    assert "users" in schema
    assert "products" in schema
    assert "product_id" in schema
    assert "refund_amount" in schema
    assert rows
    assert {"user_name", "product_name", "total_amount"} <= rows[0].keys()


def test_database_initializes_query_logs_and_can_write_log(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()

    db.log_query(
        question="最近 30 天销售额最高的 5 个商品是什么？",
        sql="SELECT product_name FROM orders LIMIT 5",
        trusted_answer=True,
        chart_type="bar",
        row_count=5,
        error=None,
        duration_ms=12,
    )
    rows = db.execute_select("SELECT trusted_answer, chart_type, row_count FROM query_logs LIMIT 1")

    assert rows == [{"trusted_answer": 1, "chart_type": "bar", "row_count": 5}]


def test_database_lists_query_logs_and_updates_feedback(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()
    db.log_query(
        question="哪个商品品类的退款率最高？",
        sql="SELECT category FROM orders LIMIT 5",
        trusted_answer=True,
        chart_type="bar",
        row_count=5,
        error=None,
        duration_ms=20,
    )

    log_id = db.list_query_logs()[0]["id"]
    assert db.update_query_feedback(log_id, feedback="dislike", note="口径需要确认") is True

    row = db.list_query_logs()[0]
    assert row["feedback"] == "dislike"
    assert row["feedback_note"] == "口径需要确认"


def test_database_saves_session_messages_and_returns_context(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()

    session_id = db.create_session()
    db.save_chat_message(
        session_id=session_id,
        question="请按商品统计销售额排名",
        sql="SELECT product_name FROM orders LIMIT 5",
        answer="商品销售额 Top 5。",
    )

    context = db.get_recent_session_context(session_id)

    assert session_id
    assert "请按商品统计销售额排名" in context
    assert "SELECT product_name" in context


def test_database_returns_query_stats(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()
    db.log_query(
        question="请按商品统计销售额排名",
        sql="SELECT product_name FROM orders LIMIT 5",
        trusted_answer=False,
        chart_type="bar",
        row_count=5,
        error=None,
        duration_ms=10,
    )
    db.log_query(
        question="请删除所有订单数据",
        sql="DELETE FROM orders",
        trusted_answer=False,
        chart_type="",
        row_count=0,
        error="SQL 不安全",
        duration_ms=20,
    )

    stats = db.get_query_stats()

    assert stats["total_queries"] == 2
    assert stats["success_queries"] == 1
    assert stats["failed_queries"] == 1
    assert stats["chart_type_counts"]["bar"] == 1
    assert stats["top_questions"][0]["count"] == 1
