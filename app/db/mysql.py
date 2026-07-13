from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlsplit


class MySQLClient:
    def __init__(
        self,
        database_url: str,
        connect: Callable[..., Any] | None = None,
        connect_timeout: int = 5,
    ) -> None:
        parsed = urlsplit(database_url)
        if parsed.scheme != "mysql" or not parsed.hostname or not parsed.username or not parsed.path.strip("/"):
            raise ValueError("MySQL database_url 格式应为 mysql://user:password@host:3306/database")

        self.host = parsed.hostname
        self.port = parsed.port or 3306
        self.user = unquote(parsed.username)
        self.password = unquote(parsed.password or "")
        self.database = parsed.path.strip("/")
        self.charset = parse_qs(parsed.query).get("charset", ["utf8mb4"])[0]
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

            missing_column_whitelists = [
                table for table in allowed_tables if not allowed_columns.get(table)
            ]
            if missing_column_whitelists:
                return {
                    "ok": False,
                    "message": "MySQL 数据源必须为每个白名单表显式配置 allowed_columns",
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
            return {"ok": False, "message": f"MySQL 连接失败：{self._sanitize(str(exc))}"}

        return {"ok": True, "message": "MySQL 数据源连接正常"}

    def list_tables(self) -> list[str]:
        rows = self.execute_select(
            """
            SELECT table_name AS name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
        return [row["name"] for row in rows]

    def list_columns(self, table_name: str) -> list[dict[str, str]]:
        sql = """
        SELECT column_name AS name, column_type AS type
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
        ORDER BY ordinal_position
        """
        try:
            with self._connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (table_name,))
                    return [{"name": row[0], "type": row[1]} for row in cursor.fetchall()]
        except Exception as exc:
            raise RuntimeError(self._sanitize(str(exc))) from exc

    def execute_select(
        self,
        sql: str,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        try:
            with self._connection(timeout_seconds) as conn:
                with conn.cursor() as cursor:
                    if timeout_seconds is not None:
                        cursor.execute(
                            "SET SESSION MAX_EXECUTION_TIME = %s",
                            (max(1, int(timeout_seconds * 1000)),),
                        )
                    cursor.execute(sql)
                    columns = [self._column_name(column) for column in (cursor.description or [])]
                    return [
                        {column: self._json_value(value) for column, value in zip(columns, row)}
                        for row in cursor.fetchall()
                    ]
        except Exception as exc:
            if self._is_timeout(exc):
                raise TimeoutError("SQL 执行超时") from exc
            raise RuntimeError(self._sanitize(str(exc))) from exc

    def _connection(self, timeout_seconds: float | None = None):
        io_timeout = max(1, int(timeout_seconds or self.connect_timeout))
        return self.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset=self.charset,
            connect_timeout=self.connect_timeout,
            read_timeout=io_timeout,
            write_timeout=io_timeout,
            autocommit=True,
        )

    @staticmethod
    def _default_connect(**kwargs):
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("缺少 PyMySQL，请先安装 requirements.txt") from exc
        return pymysql.connect(**kwargs)

    @staticmethod
    def _column_name(column: Any) -> str:
        return getattr(column, "name", column[0])

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        return value

    @staticmethod
    def _is_timeout(exc: Exception) -> bool:
        code = exc.args[0] if exc.args else None
        message = str(exc).lower()
        return code == 3024 or "timed out" in message or "timeout" in message

    def _sanitize(self, message: str) -> str:
        if not self.password:
            return message
        return message.replace(self.password, "***").replace(quote(self.password, safe=""), "***")
