import sqlite3

from app.db.database import SQLiteDatabase
import pytest


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


def test_database_seeds_enough_demo_data_for_analytics(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()

    counts = db.execute_select(
        """
        SELECT
            (SELECT COUNT(*) FROM users) AS user_count,
            (SELECT COUNT(*) FROM products) AS product_count,
            (SELECT COUNT(*) FROM orders) AS order_count,
            (SELECT COUNT(DISTINCT DATE(created_at)) FROM orders) AS active_days
        """
    )[0]

    assert counts["user_count"] >= 80
    assert counts["product_count"] >= 30
    assert counts["order_count"] >= 1000
    assert counts["active_days"] >= 90


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


def test_database_lists_only_successful_liked_historical_qa(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()
    source_id = db.get_default_data_source()["id"]

    db.log_query(
        question="最近 30 天销售额是多少？",
        sql="SELECT SUM(amount) FROM orders",
        trusted_answer=False,
        chart_type="",
        row_count=1,
        error=None,
        duration_ms=10,
        data_source_id=source_id,
        sql_explanation="汇总最近 30 天订单金额。",
        answer="最近 30 天销售额为 100 万元。",
    )
    liked_log_id = db.list_query_logs()[0]["id"]
    db.update_query_feedback(liked_log_id, feedback="like")

    db.log_query(
        question="失败的问题",
        sql="SELECT missing FROM orders",
        trusted_answer=False,
        chart_type="",
        row_count=0,
        error="字段不存在",
        duration_ms=10,
        data_source_id=source_id,
        sql_explanation="查询不存在的字段。",
        answer="查询失败。",
    )
    failed_log_id = db.list_query_logs()[0]["id"]
    db.update_query_feedback(failed_log_id, feedback="like")

    db.log_query(
        question="未点赞的问题",
        sql="SELECT COUNT(*) FROM orders",
        trusted_answer=False,
        chart_type="",
        row_count=1,
        error=None,
        duration_ms=10,
        data_source_id=source_id,
        sql_explanation="统计订单数。",
        answer="共有 1000 笔订单。",
    )

    assert db.list_high_quality_historical_qa(source_id) == [
        {
            "id": liked_log_id,
            "question": "最近 30 天销售额是多少？",
            "sql": "SELECT SUM(amount) FROM orders",
            "sql_explanation": "汇总最近 30 天订单金额。",
            "answer": "最近 30 天销售额为 100 万元。",
            "data_source_id": source_id,
        }
    ]


def test_database_skips_liked_historical_qa_with_empty_answer(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()
    source_id = db.get_default_data_source()["id"]

    db.log_query(
        question="最近 30 天销售额是多少？",
        sql="SELECT SUM(amount) FROM orders",
        trusted_answer=False,
        chart_type="",
        row_count=1,
        error=None,
        duration_ms=10,
        data_source_id=source_id,
        sql_explanation="汇总最近 30 天订单金额。",
        answer="",
    )
    log_id = db.list_query_logs()[0]["id"]
    db.update_query_feedback(log_id, feedback="like")

    assert db.list_high_quality_historical_qa(source_id) == []


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


def test_database_initializes_default_data_source(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()

    source = db.get_default_data_source()

    assert source["name"] == "default_sqlite"
    assert source["db_type"] == "sqlite"
    assert set(source["allowed_tables"]) == {"orders", "users", "products"}
    assert source["is_default"] is True


def test_database_creates_lists_and_tests_data_source(tmp_path):
    database_path = tmp_path / "orders.db"
    db = SQLiteDatabase(database_path)
    db.initialize()

    created = db.create_data_source(
        name="orders_only",
        db_type="sqlite",
        database_url=str(database_path),
        allowed_tables=["orders"],
    )
    sources = db.list_data_sources()
    test_result = db.test_data_source(created["id"])

    assert created["allowed_tables"] == ["orders"]
    assert any(source["name"] == "orders_only" for source in sources)
    assert test_result["ok"] is True


def test_database_sqlite_source_test_fails_when_whitelist_table_missing(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()
    source = db.create_data_source(
        name="bad_sqlite",
        db_type="sqlite",
        database_url=str(tmp_path / "orders.db"),
        allowed_tables=["missing_table"],
    )

    result = db.test_data_source(source["id"])

    assert result["ok"] is False
    assert "missing_table" in result["message"]


def test_database_creates_data_source_with_column_whitelist_and_catalog(tmp_path):
    database_path = tmp_path / "orders.db"
    db = SQLiteDatabase(database_path)
    db.initialize()

    source = db.create_data_source(
        name="products_public",
        db_type="sqlite",
        database_url=str(database_path),
        allowed_tables=["products"],
        allowed_columns={"products": ["id", "product_name", "brand"]},
    )
    tables = db.list_catalog_tables(source["id"])
    columns = db.list_catalog_columns("products", source["id"])

    assert source["allowed_columns"]["products"] == ["id", "product_name", "brand"]
    assert tables == [{"name": "products", "description": "商品维度表", "queryable": True}]
    assert next(column for column in columns if column["name"] == "brand")["queryable"] is True
    assert next(column for column in columns if column["name"] == "cost_price")["queryable"] is False


def test_database_catalog_can_include_non_queryable_schema(tmp_path):
    database_path = tmp_path / "orders.db"
    db = SQLiteDatabase(database_path)
    db.initialize()
    source = db.create_data_source(
        name="orders_public",
        db_type="sqlite",
        database_url=str(database_path),
        allowed_tables=["orders"],
        allowed_columns={"orders": ["id", "amount"]},
    )

    public_tables = db.list_catalog_tables(source["id"])
    all_tables = db.list_catalog_tables(source["id"], include_non_queryable=True)
    product_columns = db.list_catalog_columns(
        "products",
        source["id"],
        include_non_queryable=True,
    )

    assert [table["name"] for table in public_tables] == ["orders"]
    assert next(table for table in all_tables if table["name"] == "orders")["queryable"] is True
    assert next(table for table in all_tables if table["name"] == "products")["queryable"] is False
    assert product_columns
    assert all(column["queryable"] is False for column in product_columns)


def test_database_catalog_introspects_selected_sqlite_source(tmp_path):
    db = SQLiteDatabase(tmp_path / "catalog.db")
    db.initialize()
    source_path = tmp_path / "external.db"
    with sqlite3.connect(source_path) as conn:
        conn.executescript(
            """
            CREATE TABLE sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                region TEXT NOT NULL,
                revenue REAL NOT NULL
            );
            CREATE TABLE inventory (
                id INTEGER PRIMARY KEY,
                sku TEXT NOT NULL
            );
            """
        )
    source = db.create_data_source(
        name="external_sqlite",
        db_type="sqlite",
        database_url=str(source_path),
        allowed_tables=["sales"],
        allowed_columns={"sales": ["id", "revenue"]},
    )

    public_tables = db.list_catalog_tables(source["id"])
    all_tables = db.list_catalog_tables(source["id"], include_non_queryable=True)
    inventory_columns = db.list_catalog_columns(
        "inventory",
        source["id"],
        include_non_queryable=True,
    )

    assert public_tables == [{"name": "sales", "description": "", "queryable": True}]
    assert all_tables == [
        {"name": "inventory", "description": "", "queryable": False},
        {"name": "sales", "description": "", "queryable": True},
    ]
    assert [column["name"] for column in inventory_columns] == ["id", "sku"]
    assert all(column["queryable"] is False for column in inventory_columns)
    assert db.list_catalog_columns("missing", source["id"], include_non_queryable=True) == []


def test_database_updates_data_source_and_switches_default(tmp_path):
    database_path = tmp_path / "orders.db"
    db = SQLiteDatabase(database_path)
    db.initialize()
    original_default = db.get_default_data_source()
    source = db.create_data_source(
        name="products_source",
        db_type="sqlite",
        database_url=str(database_path),
        allowed_tables=["orders"],
    )

    updated = db.update_data_source(
        source["id"],
        database_url=str(tmp_path / "updated.db"),
        allowed_tables=["products"],
        allowed_columns={"products": ["id", "product_name"]},
        is_default=True,
    )

    assert updated is not None
    assert updated["database_url"] == str(tmp_path / "updated.db")
    assert updated["allowed_tables"] == ["products"]
    assert updated["allowed_columns"] == {"products": ["id", "product_name"]}
    assert updated["is_default"] is True
    assert db.get_data_source(original_default["id"])["is_default"] is False
    assert db.get_default_data_source()["id"] == source["id"]


def test_database_rejects_unsetting_or_deleting_default_data_source(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()
    default_source = db.get_default_data_source()

    with pytest.raises(ValueError, match="默认数据源"):
        db.update_data_source(default_source["id"], is_default=False)

    with pytest.raises(ValueError, match="默认数据源"):
        db.delete_data_source(default_source["id"])

    assert db.get_data_source(default_source["id"]) is not None


def test_database_deletes_non_default_source_and_rejects_masked_password(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()
    source = db.create_data_source(
        name="mysql_source",
        db_type="mysql",
        database_url="mysql://user:secret@localhost:3306/datapilot",
        allowed_tables=["orders"],
        allowed_columns={"orders": ["id", "amount"]},
    )

    with pytest.raises(ValueError, match="完整连接地址"):
        db.update_data_source(
            source["id"],
            database_url="mysql://user:***@localhost:3306/datapilot",
        )

    assert db.delete_data_source(source["id"]) is True
    assert db.get_data_source(source["id"]) is None
    assert db.delete_data_source(source["id"]) is False


def test_database_update_preserves_unspecified_column_whitelists(tmp_path):
    database_path = tmp_path / "orders.db"
    db = SQLiteDatabase(database_path)
    db.initialize()
    source = db.create_data_source(
        name="partial_columns",
        db_type="sqlite",
        database_url=str(database_path),
        allowed_tables=["orders", "products"],
        allowed_columns={"orders": ["id"], "products": ["id"]},
    )

    updated = db.update_data_source(
        source["id"],
        allowed_columns={"orders": ["id", "amount"]},
    )

    assert updated["allowed_columns"] == {
        "orders": ["id", "amount"],
        "products": ["id"],
    }


def test_database_execute_select_can_timeout(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()

    with pytest.raises(TimeoutError):
        db.execute_select(
            """
            WITH RECURSIVE cnt(x) AS (
                SELECT 1
                UNION ALL
                SELECT x + 1 FROM cnt WHERE x < 100000000
            )
            SELECT x FROM cnt
            """,
            timeout_seconds=0,
        )


def test_database_initializes_default_metrics(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()

    metrics = db.list_metrics()

    names = {metric["name"] for metric in metrics}
    assert {"销售额", "退款率", "客单价", "毛利", "订单数"} <= names


def test_database_can_create_update_and_delete_metric(tmp_path):
    db = SQLiteDatabase(tmp_path / "orders.db")
    db.initialize()

    created = db.create_metric(
        metric_key="repeat_order_count",
        name="复购订单数",
        expression="COUNT(orders.id)",
        description="重复购买订单数量。",
    )
    assert created["enabled"] is True

    updated = db.update_metric(created["id"], enabled=False)
    enabled_names = {metric["name"] for metric in db.list_metrics(enabled_only=True)}

    assert updated is not None
    assert updated["enabled"] is False
    assert "复购订单数" not in enabled_names
    assert db.delete_metric(created["id"]) is True
