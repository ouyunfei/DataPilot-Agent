from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable


class PostgresClient:
    def __init__(
        self,
        database_url: str,
        connect: Callable[..., Any] | None = None,
        connect_timeout: int = 5,
    ) -> None:
        self.database_url = database_url
        self.connect = connect or self._default_connect
        self.connect_timeout = connect_timeout

    def test_connection(
        self,
        allowed_tables: list[str],
        allowed_columns: dict[str, list[str]],
    ) -> dict[str, Any]:
        try:
            existing_tables = set(self.list_tables())
            missing_tables = set(allowed_tables) - existing_tables
            if missing_tables:
                return {
                    "ok": False,
                    "message": f"白名单表不存在：{'、'.join(sorted(missing_tables))}",
                }

            for table, columns in allowed_columns.items():
                existing_columns = {column["name"] for column in self.list_columns(table)}
                missing_columns = set(columns) - existing_columns
                if missing_columns:
                    return {
                        "ok": False,
                        "message": f"{table} 白名单字段不存在：{'、'.join(sorted(missing_columns))}",
                    }
        except Exception as exc:
            return {"ok": False, "message": f"PostgreSQL 连接失败：{exc}"}

        return {"ok": True, "message": "PostgreSQL 数据源连接正常"}

    def list_tables(self) -> list[str]:
        sql = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
        return [row["table_name"] for row in self.execute_select(sql)]

    def list_columns(self, table_name: str) -> list[dict[str, str]]:
        sql = """
        SELECT column_name AS name, data_type AS type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
        ORDER BY ordinal_position
        """
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (table_name,))
                return [
                    {"name": row[0], "type": row[1]}
                    for row in cursor.fetchall()
                ]

    def execute_select(
        self,
        sql: str,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        with self._connection() as conn:
            with conn.cursor() as cursor:
                if timeout_seconds is not None:
                    cursor.execute(f"SET statement_timeout = {int(timeout_seconds * 1000)}")
                cursor.execute(sql)
                columns = [self._column_name(column) for column in (cursor.description or [])]
                return [
                    {column: self._json_value(value) for column, value in zip(columns, row)}
                    for row in cursor.fetchall()
                ]

    def _connection(self):
        return self.connect(self.database_url, connect_timeout=self.connect_timeout)

    @staticmethod
    def _default_connect(database_url: str, connect_timeout: int):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("缺少 psycopg，请先安装 requirements.txt") from exc
        return psycopg.connect(database_url, connect_timeout=connect_timeout)

    @staticmethod
    def _column_name(column: Any) -> str:
        return getattr(column, "name", column[0])

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        return value
