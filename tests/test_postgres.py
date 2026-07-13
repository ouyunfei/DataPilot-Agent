from decimal import Decimal
import json

from app.db.postgres import PostgresClient


class FakeCursor:
    def __init__(self, rows=None, description=None):
        self.rows = rows or []
        self.description = description
        self.executed: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


def test_postgres_client_executes_select_and_returns_dict_rows():
    cursor = FakeCursor(rows=[("无线鼠标", 128.5)], description=[("product_name",), ("amount",)])
    client = PostgresClient(
        "postgresql://datapilot:datapilot123@localhost:5432/datapilot",
        connect=lambda url, connect_timeout: FakeConnection(cursor),
    )

    rows = client.execute_select("SELECT product_name, amount FROM orders LIMIT 1", timeout_seconds=5)

    assert rows == [{"product_name": "无线鼠标", "amount": 128.5}]
    assert any("statement_timeout" in sql for sql in cursor.executed)


def test_postgres_client_converts_decimal_rows_for_json_response():
    cursor = FakeCursor(rows=[("人体工学椅", Decimal("3198.00"))], description=[("product_name",), ("total_sales",)])
    client = PostgresClient(
        "postgresql://datapilot:datapilot123@localhost:5432/datapilot",
        connect=lambda url, connect_timeout: FakeConnection(cursor),
    )

    rows = client.execute_select("SELECT product_name, total_sales FROM orders LIMIT 1")

    assert rows == [{"product_name": "人体工学椅", "total_sales": 3198.0}]
    json.dumps(rows, ensure_ascii=False)


def test_postgres_client_checks_tables_and_columns():
    class CatalogClient(PostgresClient):
        def list_tables(self):
            return ["orders"]

        def list_columns(self, table_name):
            return [
                {"name": "id", "type": "integer"},
                {"name": "amount", "type": "numeric"},
            ]

    client = CatalogClient("postgresql://example")

    result = client.test_connection(
        allowed_tables=["orders"],
        allowed_columns={"orders": ["id", "amount"]},
    )

    assert result == {"ok": True, "message": "PostgreSQL 数据源连接正常"}
