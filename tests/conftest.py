import os


os.environ.setdefault("META_DATABASE_URL", "mysql://user:secret@localhost:3306/datapilot")
os.environ.setdefault("DEFAULT_MYSQL_DATA_SOURCE_URL", os.environ["META_DATABASE_URL"])


class FakeBusinessMySQLClient:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def test_connection(self, allowed_tables, allowed_columns):
        existing_tables = set(self.list_tables())
        missing = set(allowed_tables) - existing_tables
        if missing:
            return {"ok": False, "message": f"白名单表不存在：{'、'.join(sorted(missing))}"}
        for table, columns in allowed_columns.items():
            existing_columns = {column["name"] for column in self.list_columns(table)}
            missing_columns = set(columns) - existing_columns
            if missing_columns:
                return {"ok": False, "message": f"{table} 白名单字段不存在：{'、'.join(sorted(missing_columns))}"}
        return {"ok": True, "message": "MySQL 数据源连接正常"}

    def list_tables(self):
        return ["orders", "products", "users"]

    def list_columns(self, table_name):
        columns = {
            "orders": [
                ("id", "int"),
                ("user_id", "int"),
                ("product_id", "int"),
                ("product_name", "varchar(100)"),
                ("category", "varchar(50)"),
                ("city", "varchar(50)"),
                ("amount", "decimal(10,2)"),
                ("status", "varchar(20)"),
                ("created_at", "date"),
                ("refund_amount", "decimal(10,2)"),
            ],
            "users": [
                ("id", "int"),
                ("name", "varchar(100)"),
                ("city", "varchar(50)"),
                ("level", "varchar(20)"),
                ("registered_at", "date"),
            ],
            "products": [
                ("id", "int"),
                ("product_name", "varchar(100)"),
                ("category", "varchar(50)"),
                ("brand", "varchar(50)"),
                ("cost_price", "decimal(10,2)"),
                ("list_price", "decimal(10,2)"),
            ],
        }
        return [{"name": name, "type": typ} for name, typ in columns.get(table_name, [])]

    def execute_select(self, sql, timeout_seconds=None):
        if "FROM users" in sql:
            return [{"id": 1, "name": "张三"}]
        if "cost_price" in sql:
            return [{"cost_price": 89}]
        return [
            {"product_name": "无线鼠标", "total_amount": 128.5, "order_count": 2},
            {"product_name": "机械键盘", "total_amount": 99.0, "order_count": 1},
        ]


def pytest_configure(config):
    from tests.fakes import FakeMySQLConnection
    import app.main as main
    from app.db import database
    from app.db.meta_mysql import MySQLMetaDatabase

    database.MySQLClient = FakeBusinessMySQLClient

    class TestMySQLMetaDatabase(MySQLMetaDatabase):
        def __init__(self, database_url: str) -> None:
            self.fake = FakeMySQLConnection()
            super().__init__(database_url, connect=lambda **_kwargs: self.fake)

    main.MySQLMetaDatabase = TestMySQLMetaDatabase
