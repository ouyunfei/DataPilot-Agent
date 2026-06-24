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
