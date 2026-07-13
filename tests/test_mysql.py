from decimal import Decimal

from app.db.mysql import MySQLClient


class FakeCursor:
    def __init__(self, rows=None, description=None, error=None):
        self.rows = rows or []
        self.description = description
        self.error = error
        self.executed: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.error and not sql.strip().upper().startswith("SET SESSION"):
            raise self.error

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


def test_mysql_client_executes_select_and_returns_dict_rows():
    cursor = FakeCursor(
        rows=[("无线鼠标", 128.5)],
        description=[("product_name",), ("amount",)],
    )
    connection_kwargs = {}

    def connect(**kwargs):
        connection_kwargs.update(kwargs)
        return FakeConnection(cursor)

    client = MySQLClient(
        "mysql://datapilot_ro:secret@localhost:3306/datapilot",
        connect=connect,
    )

    rows = client.execute_select(
        "SELECT product_name, amount FROM orders LIMIT 1",
        timeout_seconds=5,
    )

    assert rows == [{"product_name": "无线鼠标", "amount": 128.5}]
    assert connection_kwargs["host"] == "localhost"
    assert connection_kwargs["database"] == "datapilot"
    assert any("MAX_EXECUTION_TIME" in sql for sql, _ in cursor.executed)


def test_mysql_client_converts_decimal_rows_for_json_response():
    cursor = FakeCursor(
        rows=[("人体工学椅", Decimal("3198.00"))],
        description=[("product_name",), ("total_sales",)],
    )
    client = MySQLClient(
        "mysql://datapilot_ro:secret@localhost:3306/datapilot",
        connect=lambda **kwargs: FakeConnection(cursor),
    )

    rows = client.execute_select("SELECT product_name, total_sales FROM orders LIMIT 1")

    assert rows == [{"product_name": "人体工学椅", "total_sales": 3198.0}]


def test_mysql_client_lists_information_schema_tables():
    cursor = FakeCursor(
        rows=[("orders",), ("products",), ("users",)],
        description=[("name",)],
    )
    client = MySQLClient(
        "mysql://datapilot_ro:secret@localhost:3306/datapilot",
        connect=lambda **kwargs: FakeConnection(cursor),
    )

    assert client.list_tables() == ["orders", "products", "users"]
    assert "table_name AS name" in cursor.executed[0][0]


def test_mysql_client_checks_tables_and_columns():
    class CatalogClient(MySQLClient):
        def list_tables(self):
            return ["orders"]

        def list_columns(self, table_name):
            return [
                {"name": "id", "type": "int"},
                {"name": "amount", "type": "decimal"},
            ]

    client = CatalogClient("mysql://user:secret@localhost:3306/datapilot")

    result = client.test_connection(
        allowed_tables=["orders"],
        allowed_columns={"orders": ["id", "amount"]},
    )

    assert result == {"ok": True, "message": "MySQL 数据源连接正常"}


def test_mysql_client_reports_missing_table_and_column():
    class MissingTableClient(MySQLClient):
        def list_tables(self):
            return ["orders"]

    missing_table = MissingTableClient("mysql://user:secret@localhost:3306/datapilot")

    table_result = missing_table.test_connection(["users"], {"users": ["id"]})

    assert table_result["ok"] is False
    assert "users" in table_result["message"]

    class MissingColumnClient(MySQLClient):
        def list_tables(self):
            return ["orders"]

        def list_columns(self, table_name):
            return [{"name": "id", "type": "int"}]

    missing_column = MissingColumnClient("mysql://user:secret@localhost:3306/datapilot")

    column_result = missing_column.test_connection(
        ["orders"],
        {"orders": ["id", "amount"]},
    )

    assert column_result["ok"] is False
    assert "amount" in column_result["message"]


def test_mysql_client_rejects_table_without_column_whitelist():
    class CatalogClient(MySQLClient):
        def list_tables(self):
            return ["orders"]

    client = CatalogClient("mysql://user:secret@localhost:3306/datapilot")

    result = client.test_connection(["orders"], {})

    assert result["ok"] is False
    assert "allowed_columns" in result["message"]


def test_mysql_client_hides_password_in_connection_errors():
    def fail_connect(**kwargs):
        raise RuntimeError("connection failed for secret")

    client = MySQLClient(
        "mysql://user:secret@localhost:3306/datapilot",
        connect=fail_connect,
    )

    result = client.test_connection(["orders"], {"orders": ["id"]})

    assert result["ok"] is False
    assert "secret" not in result["message"]


def test_mysql_client_maps_query_timeout_to_timeout_error():
    timeout_error = RuntimeError(3024, "Query execution was interrupted")
    cursor = FakeCursor(error=timeout_error)
    client = MySQLClient(
        "mysql://user:secret@localhost:3306/datapilot",
        connect=lambda **kwargs: FakeConnection(cursor),
    )

    try:
        client.execute_select("SELECT id FROM orders LIMIT 1", timeout_seconds=1)
    except TimeoutError as exc:
        assert str(exc) == "SQL 执行超时"
    else:
        raise AssertionError("MySQL 查询超时应转换为 TimeoutError")
