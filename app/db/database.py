from __future__ import annotations

import random
import sqlite3
import uuid
import json
import re
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

from app.db.mysql import MySQLClient
from app.db.postgres import PostgresClient


ORDER_FIELD_DESCRIPTIONS = {
    "id": "订单 ID，主键",
    "user_id": "用户 ID",
    "product_id": "商品 ID，关联 products.id",
    "product_name": "商品名称",
    "category": "商品品类",
    "city": "下单城市",
    "amount": "订单金额，单位：元",
    "status": "订单状态，paid 表示已支付，refunded 表示已退款，cancelled 表示已取消",
    "created_at": "下单日期，ISO 日期格式",
    "refund_amount": "退款金额，未退款为 0",
}

USER_FIELD_DESCRIPTIONS = {
    "id": "用户 ID，主键",
    "name": "用户姓名",
    "city": "用户常驻城市",
    "level": "用户等级，包含 普通、银卡、金卡、黑金",
    "registered_at": "用户注册日期",
}

PRODUCT_FIELD_DESCRIPTIONS = {
    "id": "商品 ID，主键",
    "product_name": "商品名称",
    "category": "商品品类",
    "brand": "商品品牌",
    "cost_price": "成本价，单位：元",
    "list_price": "标价，单位：元",
}
TABLE_DESCRIPTIONS = {
    "orders": ("订单事实表", ORDER_FIELD_DESCRIPTIONS),
    "users": ("用户维度表", USER_FIELD_DESCRIPTIONS),
    "products": ("商品维度表", PRODUCT_FIELD_DESCRIPTIONS),
}

DEFAULT_METRICS = [
    {
        "metric_key": "sales_amount",
        "name": "销售额",
        "expression": "SUM(orders.amount)",
        "description": "已支付订单金额总和。",
    },
    {
        "metric_key": "refund_rate",
        "name": "退款率",
        "expression": "退款订单数 / 总订单数",
        "description": "refund_amount > 0 或 status = 'refunded' 的订单占比。",
    },
    {
        "metric_key": "average_order_value",
        "name": "客单价",
        "expression": "SUM(orders.amount) / COUNT(DISTINCT orders.id)",
        "description": "平均每笔订单金额。",
    },
    {
        "metric_key": "gross_profit",
        "name": "毛利",
        "expression": "SUM(orders.amount - products.cost_price)",
        "description": "订单金额减商品成本价后的金额。",
    },
    {
        "metric_key": "order_count",
        "name": "订单数",
        "expression": "COUNT(orders.id)",
        "description": "订单明细数量。",
    },
]
FORBIDDEN_METRIC_EXPRESSION_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "REPLACE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "VACUUM",
    "REINDEX",
}


class SQLiteDatabase:
    """Small SQLite wrapper for schema introspection and safe SELECT execution."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._reset_incompatible_schema(conn)
            self._create_tables(conn)
            self._seed_if_empty(conn)
            self._seed_default_data_source(conn)
            self._seed_default_metrics(conn)

    def get_schema_description(
        self,
        allowed_tables: list[str] | None = None,
        allowed_columns: dict[str, list[str]] | None = None,
    ) -> str:
        selected_tables = set(allowed_tables or TABLE_DESCRIPTIONS.keys())
        selected_columns = {
            table: set(columns) for table, columns in (allowed_columns or {}).items()
        }
        lines = [f"当前允许查询的业务表：{'、'.join(sorted(selected_tables))}。"]
        if {"orders", "users"} <= selected_tables:
            lines.append("表关系：orders.user_id = users.id。")
        if {"orders", "products"} <= selected_tables:
            lines.append("表关系：orders.product_id = products.id。")

        with self._connect() as conn:
            for table_name, (table_comment, field_descriptions) in TABLE_DESCRIPTIONS.items():
                if table_name not in selected_tables:
                    continue
                columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
                lines.append("")
                lines.append(f"表：{table_name}（{table_comment}）")
                lines.append("字段：")
                for column in columns:
                    name = column["name"]
                    if selected_columns and name not in selected_columns.get(table_name, set()):
                        continue
                    column_type = column["type"]
                    description = field_descriptions.get(name, "")
                    if name == "user_id" and "users" not in selected_tables:
                        description = "用户 ID"
                    if name == "product_id" and "products" not in selected_tables:
                        description = "商品 ID"
                    lines.append(f"- {name} ({column_type})：{description}")

        return "\n".join(lines)

    def get_data_source_schema_description(self, source: dict[str, Any]) -> str:
        if source["db_type"] == "sqlite":
            return (
                "SQL 方言：sqlite。\n"
                + self.get_schema_description(source["allowed_tables"], source["allowed_columns"])
            )
        if source["db_type"] == "postgresql":
            return self._get_postgres_schema_description(source)
        if source["db_type"] == "mysql":
            return self._get_mysql_schema_description(source)
        return f"SQL 方言：{source['db_type']}。\n当前阶段不支持该数据源执行查询。"

    def list_tables(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
            return [row["name"] for row in rows]

    def execute_select(
        self,
        sql: str,
        database_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect(database_url) as conn:
            if timeout_seconds is not None:
                deadline = time.monotonic() + timeout_seconds

                def interrupt_when_timeout() -> int:
                    return int(time.monotonic() >= deadline)

                conn.set_progress_handler(interrupt_when_timeout, 1000)
            try:
                cursor = conn.execute(sql)
                return [dict(row) for row in cursor.fetchall()]
            except sqlite3.OperationalError as exc:
                if timeout_seconds is not None and time.monotonic() >= deadline:
                    raise TimeoutError("SQL 执行超时") from exc
                raise
            finally:
                if timeout_seconds is not None:
                    conn.set_progress_handler(None, 0)

    def execute_data_source_select(
        self,
        source: dict[str, Any],
        sql: str,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        if source["db_type"] == "sqlite":
            return self.execute_select(
                sql,
                database_url=source["database_url"],
                timeout_seconds=timeout_seconds,
            )
        if source["db_type"] == "postgresql":
            return PostgresClient(source["database_url"]).execute_select(sql, timeout_seconds)
        if source["db_type"] == "mysql":
            return MySQLClient(source["database_url"]).execute_select(sql, timeout_seconds)
        raise ValueError("当前阶段仅支持 SQLite、PostgreSQL 和 MySQL 数据源执行查询")

    @contextmanager
    def _connect(self, path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(path or self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _reset_incompatible_schema(conn: sqlite3.Connection) -> None:
        orders_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'orders'"
        ).fetchone()
        if not orders_exists:
            return

        order_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()
        }
        required_columns = {"id", "user_id", "product_id", "amount", "created_at"}
        if required_columns <= order_columns:
            return

        conn.execute("DROP TABLE IF EXISTS orders")
        conn.execute("DROP TABLE IF EXISTS users")
        conn.execute("DROP TABLE IF EXISTS products")

    @staticmethod
    def _create_tables(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                city TEXT NOT NULL,
                level TEXT NOT NULL,
                registered_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL,
                category TEXT NOT NULL,
                brand TEXT NOT NULL,
                cost_price REAL NOT NULL,
                list_price REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                category TEXT NOT NULL,
                city TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                refund_amount REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS query_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                sql TEXT NOT NULL,
                trusted_answer INTEGER NOT NULL,
                chart_type TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                error TEXT,
                feedback TEXT,
                feedback_note TEXT,
                duration_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(query_logs)").fetchall()
        }
        if "feedback" not in existing_columns:
            conn.execute("ALTER TABLE query_logs ADD COLUMN feedback TEXT")
        if "feedback_note" not in existing_columns:
            conn.execute("ALTER TABLE query_logs ADD COLUMN feedback_note TEXT")
        if "error_code" not in existing_columns:
            conn.execute("ALTER TABLE query_logs ADD COLUMN error_code TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                question TEXT NOT NULL,
                sql TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS data_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                db_type TEXT NOT NULL,
                database_url TEXT NOT NULL,
                allowed_tables TEXT NOT NULL,
                allowed_columns TEXT,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        data_source_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(data_sources)").fetchall()
        }
        if "allowed_columns" not in data_source_columns:
            conn.execute("ALTER TABLE data_sources ADD COLUMN allowed_columns TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                expression TEXT NOT NULL,
                description TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _seed_default_data_source(self, conn: sqlite3.Connection) -> None:
        exists = conn.execute("SELECT 1 FROM data_sources WHERE is_default = 1").fetchone()
        if exists:
            return

        conn.execute(
            """
            INSERT INTO data_sources (name, db_type, database_url, allowed_tables, is_default)
            VALUES (?, ?, ?, ?, 1)
            """,
            (
                "default_sqlite",
                "sqlite",
                str(self.path),
                json.dumps(["orders", "users", "products"], ensure_ascii=False),
            ),
        )

    @staticmethod
    def _seed_default_metrics(conn: sqlite3.Connection) -> None:
        conn.executemany(
            """
            INSERT OR IGNORE INTO metrics (metric_key, name, expression, description, enabled)
            VALUES (?, ?, ?, ?, 1)
            """,
            [
                (
                    metric["metric_key"],
                    metric["name"],
                    metric["expression"],
                    metric["description"],
                )
                for metric in DEFAULT_METRICS
            ],
        )

    def list_metrics(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE enabled = 1" if enabled_only else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    id, metric_key, name, expression, description,
                    enabled, created_at, updated_at
                FROM metrics
                {where}
                ORDER BY id ASC
                """
            ).fetchall()
            return [self._metric_from_row(row) for row in rows]

    def get_metric(self, metric_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id, metric_key, name, expression, description,
                    enabled, created_at, updated_at
                FROM metrics
                WHERE id = ?
                """,
                (metric_id,),
            ).fetchone()
            return self._metric_from_row(row) if row else None

    def create_metric(
        self,
        metric_key: str,
        name: str,
        expression: str,
        description: str,
        enabled: bool = True,
    ) -> dict[str, Any]:
        metric_key = metric_key.strip().lower()
        name = name.strip()
        expression = expression.strip()
        description = description.strip()
        self._validate_metric(metric_key, name, expression, description)

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO metrics (metric_key, name, expression, description, enabled)
                VALUES (?, ?, ?, ?, ?)
                """,
                (metric_key, name, expression, description, int(enabled)),
            )
            metric_id = cursor.lastrowid

        metric = self.get_metric(metric_id)
        if metric is None:
            raise ValueError("指标创建失败")
        return metric

    def update_metric(
        self,
        metric_id: int,
        metric_key: str | None = None,
        name: str | None = None,
        expression: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_metric(metric_id)
        if current is None:
            return None

        next_metric = {
            "metric_key": (metric_key.strip().lower() if metric_key is not None else current["metric_key"]),
            "name": (name.strip() if name is not None else current["name"]),
            "expression": (expression.strip() if expression is not None else current["expression"]),
            "description": (
                description.strip() if description is not None else current["description"]
            ),
            "enabled": current["enabled"] if enabled is None else enabled,
        }
        self._validate_metric(
            next_metric["metric_key"],
            next_metric["name"],
            next_metric["expression"],
            next_metric["description"],
        )

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE metrics
                SET
                    metric_key = ?,
                    name = ?,
                    expression = ?,
                    description = ?,
                    enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    next_metric["metric_key"],
                    next_metric["name"],
                    next_metric["expression"],
                    next_metric["description"],
                    int(next_metric["enabled"]),
                    metric_id,
                ),
            )
        return self.get_metric(metric_id)

    def delete_metric(self, metric_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM metrics WHERE id = ?", (metric_id,))
            return cursor.rowcount > 0

    @staticmethod
    def _validate_metric(
        metric_key: str,
        name: str,
        expression: str,
        description: str,
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", metric_key):
            raise ValueError("metric_key 必须为小写字母、数字或下划线，且以字母开头")
        if not name:
            raise ValueError("name 不能为空")
        if not expression:
            raise ValueError("expression 不能为空")
        if not description:
            raise ValueError("description 不能为空")
        upper_expression = expression.upper()
        if ";" in expression or "--" in expression or "/*" in expression or "*/" in expression:
            raise ValueError("expression 不允许包含注释或分号")
        for keyword in FORBIDDEN_METRIC_EXPRESSION_KEYWORDS:
            if re.search(rf"\b{keyword}\b", upper_expression):
                raise ValueError(f"expression 不允许包含 {keyword}")

    @staticmethod
    def _metric_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "metric_key": row["metric_key"],
            "name": row["name"],
            "expression": row["expression"],
            "description": row["description"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_data_source(
        self,
        name: str,
        db_type: str,
        database_url: str,
        allowed_tables: list[str],
        allowed_columns: dict[str, list[str]] | None = None,
        is_default: bool = False,
    ) -> dict[str, Any]:
        db_type = db_type.lower()
        if db_type not in {"sqlite", "mysql", "postgresql"}:
            raise ValueError("db_type 只支持 sqlite、mysql、postgresql")

        tables = [table.strip().lower() for table in allowed_tables if table.strip()]
        if not tables:
            raise ValueError("allowed_tables 不能为空")
        if db_type == "mysql" and (
            not allowed_columns
            or any(
                not any(column.strip() for column in allowed_columns.get(table, []))
                for table in tables
            )
        ):
            raise ValueError("MySQL 数据源必须为每个白名单表显式配置 allowed_columns")
        columns = self._normalize_allowed_columns(tables, allowed_columns)

        with self._connect() as conn:
            if is_default:
                conn.execute("UPDATE data_sources SET is_default = 0")
            cursor = conn.execute(
                """
                INSERT INTO data_sources (
                    name, db_type, database_url, allowed_tables, allowed_columns, is_default
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    db_type,
                    database_url,
                    json.dumps(tables, ensure_ascii=False),
                    json.dumps(columns, ensure_ascii=False),
                    int(is_default),
                ),
            )
            source_id = cursor.lastrowid

        source = self.get_data_source(source_id)
        if source is None:
            raise ValueError("数据源创建失败")
        return source

    def update_data_source(
        self,
        source_id: int,
        database_url: str | None = None,
        allowed_tables: list[str] | None = None,
        allowed_columns: dict[str, list[str]] | None = None,
        is_default: bool | None = None,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id, name, db_type, database_url, allowed_tables,
                    allowed_columns, is_default, created_at
                FROM data_sources
                WHERE id = ?
                """,
                (source_id,),
            ).fetchone()
            if row is None:
                return None
            current = self._data_source_from_row(row)

            next_database_url = (
                database_url if database_url is not None else current["database_url"]
            )
            if not next_database_url.strip():
                raise ValueError("database_url 不能为空")
            if ":***@" in next_database_url:
                raise ValueError("请提供包含真实密码的完整连接地址，不能提交脱敏后的 database_url")

            tables = (
                [table.strip().lower() for table in allowed_tables if table.strip()]
                if allowed_tables is not None
                else current["allowed_tables"]
            )
            if not tables:
                raise ValueError("allowed_tables 不能为空")

            columns_input = current["allowed_columns"]
            if allowed_columns is not None:
                columns_input = {**columns_input, **allowed_columns}
            if current["db_type"] == "mysql" and (
                not columns_input
                or any(
                    not any(column.strip() for column in columns_input.get(table, []))
                    for table in tables
                )
            ):
                raise ValueError("MySQL 数据源必须为每个白名单表显式配置 allowed_columns")
            columns = self._normalize_allowed_columns(tables, columns_input)

            if current["is_default"] and is_default is False:
                raise ValueError("默认数据源不能取消默认状态，请先设置其他默认数据源")
            next_is_default = current["is_default"] if is_default is None else is_default

            if is_default is True and not current["is_default"]:
                conn.execute("UPDATE data_sources SET is_default = 0")
            conn.execute(
                """
                UPDATE data_sources
                SET database_url = ?, allowed_tables = ?, allowed_columns = ?, is_default = ?
                WHERE id = ?
                """,
                (
                    next_database_url,
                    json.dumps(tables, ensure_ascii=False),
                    json.dumps(columns, ensure_ascii=False),
                    int(next_is_default),
                    source_id,
                ),
            )
            updated = conn.execute(
                """
                SELECT
                    id, name, db_type, database_url, allowed_tables,
                    allowed_columns, is_default, created_at
                FROM data_sources
                WHERE id = ?
                """,
                (source_id,),
            ).fetchone()
            return self._data_source_from_row(updated)

    def delete_data_source(self, source_id: int) -> bool:
        with self._connect() as conn:
            source = conn.execute(
                "SELECT is_default FROM data_sources WHERE id = ?",
                (source_id,),
            ).fetchone()
            if source is None:
                return False
            if source["is_default"]:
                raise ValueError("默认数据源不能删除，请先设置其他默认数据源")
            cursor = conn.execute("DELETE FROM data_sources WHERE id = ?", (source_id,))
            return cursor.rowcount > 0

    def list_data_sources(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, name, db_type, database_url, allowed_tables,
                    allowed_columns, is_default, created_at
                FROM data_sources
                ORDER BY is_default DESC, id ASC
                """
            ).fetchall()
            return [self._data_source_from_row(row) for row in rows]

    def get_data_source(self, source_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id, name, db_type, database_url, allowed_tables,
                    allowed_columns, is_default, created_at
                FROM data_sources
                WHERE id = ?
                """,
                (source_id,),
            ).fetchone()
            return self._data_source_from_row(row) if row else None

    def get_default_data_source(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id, name, db_type, database_url, allowed_tables,
                    allowed_columns, is_default, created_at
                FROM data_sources
                WHERE is_default = 1
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                raise ValueError("默认数据源不存在")
            return self._data_source_from_row(row)

    def test_data_source(self, source_id: int) -> dict[str, Any]:
        source = self.get_data_source(source_id)
        if source is None:
            return {"ok": False, "message": "数据源不存在"}

        if source["db_type"] == "postgresql":
            return PostgresClient(source["database_url"]).test_connection(
                source["allowed_tables"],
                source["allowed_columns"],
            )
        if source["db_type"] == "mysql":
            return MySQLClient(source["database_url"]).test_connection(
                source["allowed_tables"],
                source["allowed_columns"],
            )

        if source["db_type"] != "sqlite":
            return {"ok": True, "message": "配置已保存，真实连接待后续接入驱动"}

        try:
            with self._connect(source["database_url"]) as conn:
                existing_tables = {
                    row["name"]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
        except Exception as exc:
            return {"ok": False, "message": f"SQLite 连接失败：{exc}"}

        missing = set(source["allowed_tables"]) - existing_tables
        if missing:
            return {"ok": False, "message": f"白名单表不存在：{'、'.join(sorted(missing))}"}
        return {"ok": True, "message": "SQLite 数据源连接正常"}

    def list_catalog_tables(self, data_source_id: int | None = None) -> list[dict[str, Any]]:
        source = (
            self.get_data_source(data_source_id)
            if data_source_id is not None
            else self.get_default_data_source()
        )
        allowed_tables = set(source["allowed_tables"])
        if source["db_type"] == "postgresql":
            existing_tables = set(PostgresClient(source["database_url"]).list_tables())
            return [
                {
                    "name": table,
                    "description": TABLE_DESCRIPTIONS.get(table, ("", {}))[0],
                    "queryable": table in allowed_tables,
                }
                for table in sorted(existing_tables & allowed_tables)
            ]
        if source["db_type"] == "mysql":
            existing_tables = set(MySQLClient(source["database_url"]).list_tables())
            return [
                {
                    "name": table,
                    "description": TABLE_DESCRIPTIONS.get(table, ("", {}))[0],
                    "queryable": table in allowed_tables,
                }
                for table in sorted(existing_tables & allowed_tables)
            ]

        return [
            {
                "name": table,
                "description": description,
                "queryable": table in allowed_tables,
            }
            for table, (description, _) in TABLE_DESCRIPTIONS.items()
            if table in allowed_tables
        ]

    def list_catalog_columns(
        self,
        table_name: str,
        data_source_id: int | None = None,
    ) -> list[dict[str, Any]]:
        table_name = table_name.lower()

        source = (
            self.get_data_source(data_source_id)
            if data_source_id is not None
            else self.get_default_data_source()
        )
        if table_name not in source["allowed_tables"]:
            return []
        if source["db_type"] == "sqlite" and table_name not in TABLE_DESCRIPTIONS:
            return []
        allowed = set(source["allowed_columns"].get(table_name, []))
        _, field_descriptions = TABLE_DESCRIPTIONS.get(table_name, ("", {}))

        if source["db_type"] == "postgresql":
            rows = PostgresClient(source["database_url"]).list_columns(table_name)
            return [
                {
                    "name": row["name"],
                    "type": row["type"],
                    "description": field_descriptions.get(row["name"], ""),
                    "queryable": row["name"] in allowed,
                }
                for row in rows
            ]
        if source["db_type"] == "mysql":
            rows = MySQLClient(source["database_url"]).list_columns(table_name)
            return [
                {
                    "name": row["name"],
                    "type": row["type"],
                    "description": field_descriptions.get(row["name"], ""),
                    "queryable": row["name"] in allowed,
                }
                for row in rows
            ]

        with self._connect(source["database_url"]) as conn:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()

        return [
            {
                "name": row["name"],
                "type": row["type"],
                "description": field_descriptions.get(row["name"], ""),
                "queryable": row["name"] in allowed,
            }
            for row in rows
        ]

    def _get_postgres_schema_description(self, source: dict[str, Any]) -> str:
        selected_tables = set(source["allowed_tables"])
        lines = ["SQL 方言：postgresql。"]
        lines.append(f"当前允许查询的业务表：{'、'.join(sorted(selected_tables))}。")
        if {"orders", "users"} <= selected_tables:
            lines.append("表关系：orders.user_id = users.id。")
        if {"orders", "products"} <= selected_tables:
            lines.append("表关系：orders.product_id = products.id。")

        for table in source["allowed_tables"]:
            columns = self.list_catalog_columns(table, source["id"])
            if not columns:
                continue
            table_comment = TABLE_DESCRIPTIONS.get(table, ("", {}))[0]
            lines.append("")
            lines.append(f"表：{table}（{table_comment}）")
            lines.append("字段：")
            for column in columns:
                if not column["queryable"]:
                    continue
                lines.append(
                    f"- {column['name']} ({column['type']})：{column['description']}"
                )
        return "\n".join(lines)

    def _get_mysql_schema_description(self, source: dict[str, Any]) -> str:
        selected_tables = set(source["allowed_tables"])
        lines = ["SQL 方言：mysql。"]
        lines.append(f"当前允许查询的业务表：{'、'.join(sorted(selected_tables))}。")
        if {"orders", "users"} <= selected_tables:
            lines.append("表关系：orders.user_id = users.id。")
        if {"orders", "products"} <= selected_tables:
            lines.append("表关系：orders.product_id = products.id。")

        for table in source["allowed_tables"]:
            columns = self.list_catalog_columns(table, source["id"])
            if not columns:
                continue
            table_comment = TABLE_DESCRIPTIONS.get(table, ("", {}))[0]
            lines.append("")
            lines.append(f"表：{table}（{table_comment}）")
            lines.append("字段：")
            for column in columns:
                if not column["queryable"]:
                    continue
                lines.append(
                    f"- {column['name']} ({column['type']})：{column['description']}"
                )
        return "\n".join(lines)

    @staticmethod
    def _data_source_from_row(row: sqlite3.Row) -> dict[str, Any]:
        allowed_tables = json.loads(row["allowed_tables"])
        allowed_columns_raw = row["allowed_columns"]
        allowed_columns = (
            json.loads(allowed_columns_raw)
            if allowed_columns_raw
            else SQLiteDatabase._default_allowed_columns(allowed_tables)
        )
        return {
            "id": row["id"],
            "name": row["name"],
            "db_type": row["db_type"],
            "database_url": row["database_url"],
            "allowed_tables": allowed_tables,
            "allowed_columns": allowed_columns,
            "is_default": bool(row["is_default"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _default_allowed_columns(allowed_tables: list[str]) -> dict[str, list[str]]:
        return {
            table: list(TABLE_DESCRIPTIONS[table][1].keys())
            for table in allowed_tables
            if table in TABLE_DESCRIPTIONS
        }

    @staticmethod
    def _normalize_allowed_columns(
        allowed_tables: list[str],
        allowed_columns: dict[str, list[str]] | None,
    ) -> dict[str, list[str]]:
        defaults = SQLiteDatabase._default_allowed_columns(allowed_tables)
        if not allowed_columns:
            return defaults

        normalized: dict[str, list[str]] = {}
        for table in allowed_tables:
            if table not in TABLE_DESCRIPTIONS:
                normalized[table] = allowed_columns.get(table, [])
                continue
            requested = [
                column.strip().lower()
                for column in allowed_columns.get(table, [])
                if column.strip()
            ]
            normalized[table] = requested or defaults.get(table, [])
        return normalized

    def log_query(
        self,
        question: str,
        sql: str,
        trusted_answer: bool,
        chart_type: str,
        row_count: int,
        error: str | None,
        duration_ms: int,
        error_code: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO query_logs (
                    question, sql, trusted_answer, chart_type, row_count,
                    error, error_code, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question,
                    sql,
                    int(trusted_answer),
                    chart_type,
                    row_count,
                    error,
                    error_code,
                    duration_ms,
                ),
            )

    def list_query_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, question, sql, trusted_answer, chart_type, row_count,
                    error, error_code, feedback, feedback_note, duration_ms, created_at
                FROM query_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_query_feedback(self, log_id: int, feedback: str, note: str | None = None) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE query_logs
                SET feedback = ?, feedback_note = ?
                WHERE id = ?
                """,
                (feedback, note, log_id),
            )
            return cursor.rowcount > 0

    def create_session(self, session_id: str | None = None) -> str:
        session_id = session_id or str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO chat_sessions (id)
                VALUES (?)
                """,
                (session_id,),
            )
            conn.execute(
                """
                UPDATE chat_sessions
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (session_id,),
            )
        return session_id

    def save_chat_message(self, session_id: str, question: str, sql: str, answer: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (session_id, question, sql, answer)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, question, sql, answer),
            )
            conn.execute(
                """
                UPDATE chat_sessions
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (session_id,),
            )

    def get_recent_session_context(self, session_id: str, limit: int = 3) -> str:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT question, sql, answer
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, max(1, min(limit, 10))),
            ).fetchall()

        if not rows:
            return ""

        lines = ["最近会话上下文："]
        for row in reversed(rows):
            lines.append(f"- 用户问题：{row['question']}")
            lines.append(f"  SQL：{row['sql']}")
            lines.append(f"  回答：{row['answer']}")
        return "\n".join(lines)

    def get_query_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            summary = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_queries,
                    SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS success_queries,
                    SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS failed_queries,
                    SUM(trusted_answer) AS trusted_answer_queries,
                    COALESCE(ROUND(AVG(duration_ms), 2), 0) AS average_duration_ms
                FROM query_logs
                """
            ).fetchone()
            chart_rows = conn.execute(
                """
                SELECT chart_type, COUNT(*) AS count
                FROM query_logs
                WHERE chart_type != ''
                GROUP BY chart_type
                ORDER BY count DESC
                """
            ).fetchall()
            feedback_rows = conn.execute(
                """
                SELECT feedback, COUNT(*) AS count
                FROM query_logs
                WHERE feedback IS NOT NULL
                GROUP BY feedback
                ORDER BY count DESC
                """
            ).fetchall()
            question_rows = conn.execute(
                """
                SELECT question, COUNT(*) AS count
                FROM query_logs
                GROUP BY question
                ORDER BY count DESC, question ASC
                LIMIT 5
                """
            ).fetchall()
            error_code_rows = conn.execute(
                """
                SELECT error_code, COUNT(*) AS count
                FROM query_logs
                WHERE error_code IS NOT NULL
                GROUP BY error_code
                ORDER BY count DESC
                """
            ).fetchall()

        return {
            "total_queries": summary["total_queries"] or 0,
            "success_queries": summary["success_queries"] or 0,
            "failed_queries": summary["failed_queries"] or 0,
            "trusted_answer_queries": summary["trusted_answer_queries"] or 0,
            "average_duration_ms": summary["average_duration_ms"] or 0,
            "chart_type_counts": {row["chart_type"]: row["count"] for row in chart_rows},
            "feedback_counts": {row["feedback"]: row["count"] for row in feedback_rows},
            "error_code_counts": {row["error_code"]: row["count"] for row in error_code_rows},
            "top_questions": [dict(row) for row in question_rows],
        }

    def _seed_if_empty(self, conn: sqlite3.Connection) -> None:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

        if user_count < 80:
            conn.executemany(
                """
                INSERT INTO users (id, name, city, level, registered_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                self._build_seed_users(),
            )
        if product_count < 30:
            conn.executemany(
                """
                INSERT INTO products (id, product_name, category, brand, cost_price, list_price)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                self._build_seed_products(),
            )
        if order_count < 1000:
            products = conn.execute(
                "SELECT id, product_name, category, list_price FROM products ORDER BY id"
            ).fetchall()
            users = conn.execute("SELECT id, city FROM users ORDER BY id").fetchall()
            conn.executemany(
                """
                INSERT INTO orders (
                    id, user_id, product_id, product_name, category, city, amount,
                    status, created_at, refund_amount
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                self._build_seed_orders(products=products, users=users),
            )

    @staticmethod
    def _build_seed_users() -> list[tuple[Any, ...]]:
        cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "苏州", "西安", "重庆", "长沙"]
        levels = ["普通", "银卡", "金卡", "黑金"]
        today = date.today()
        rows: list[tuple[Any, ...]] = []
        for index in range(1, 81):
            rows.append(
                (
                    1000 + index,
                    f"用户{index:02d}",
                    cities[index % len(cities)],
                    levels[index % len(levels)],
                    (today - timedelta(days=120 + index * 7)).isoformat(),
                )
            )
        return rows

    @staticmethod
    def _build_seed_products() -> list[tuple[Any, ...]]:
        return [
            (1, "无线鼠标", "数码配件", "LogiPlus", 89, 199),
            (2, "机械键盘", "数码配件", "KeyMaster", 260, 499),
            (3, "蓝牙耳机", "数码配件", "SoundBee", 180, 399),
            (4, "空气炸锅", "家用电器", "HomePro", 390, 699),
            (5, "智能电饭煲", "家用电器", "HomePro", 310, 599),
            (6, "咖啡机", "家用电器", "BeanLab", 790, 1299),
            (7, "冲锋衣", "服饰鞋包", "TrailGo", 430, 899),
            (8, "跑步鞋", "服饰鞋包", "RunPeak", 260, 599),
            (9, "保温杯", "生活日用", "DailyUp", 45, 129),
            (10, "人体工学椅", "办公家具", "WorkWell", 880, 1599),
            (11, "显示器", "数码配件", "ViewMax", 760, 1299),
            (12, "移动硬盘", "数码配件", "DataBox", 320, 699),
            (13, "扫地机器人", "家用电器", "HomePro", 1190, 2299),
            (14, "净水器", "家用电器", "PureFlow", 980, 1899),
            (15, "羽绒服", "服饰鞋包", "WarmGo", 520, 1099),
            (16, "双肩包", "服饰鞋包", "UrbanPack", 150, 399),
            (17, "洗发水", "美妆个护", "CarePlus", 38, 89),
            (18, "护肤套装", "美妆个护", "GlowLab", 210, 499),
            (19, "坚果礼盒", "食品饮料", "SnackFun", 90, 199),
            (20, "咖啡豆", "食品饮料", "BeanLab", 78, 169),
            (21, "婴儿推车", "母婴用品", "BabyJoy", 650, 1399),
            (22, "儿童积木", "母婴用品", "KidStar", 80, 199),
            (23, "瑜伽垫", "运动户外", "FitNow", 55, 129),
            (24, "露营帐篷", "运动户外", "TrailGo", 430, 899),
            (25, "商务笔记本", "图书文具", "PaperPro", 28, 69),
            (26, "钢笔礼盒", "图书文具", "WriteWell", 120, 299),
            (27, "升降桌", "办公家具", "WorkWell", 900, 1899),
            (28, "文件柜", "办公家具", "OfficePro", 300, 799),
            (29, "智能手表", "数码配件", "TechTime", 450, 999),
            (30, "电动牙刷", "美妆个护", "CarePlus", 120, 299),
        ]

    @staticmethod
    def _build_seed_orders(
        products: list[sqlite3.Row],
        users: list[sqlite3.Row],
    ) -> list[tuple[Any, ...]]:
        random.seed(202409)
        today = date.today()
        rows: list[tuple[Any, ...]] = []

        for order_id in range(1, 1001):
            product = products[(order_id * 7) % len(products)]
            user = users[(order_id * 13) % len(users)]
            created_at = today - timedelta(days=order_id % 120)
            status = "paid"
            refund_amount = 0.0
            if order_id % 31 == 0:
                status = "cancelled"
            elif order_id % 19 == 0:
                status = "refunded"

            amount = round(float(product["list_price"]) * random.uniform(0.85, 1.35), 2)
            if status == "cancelled":
                amount = 0.0
            if status == "refunded":
                refund_amount = amount
            rows.append(
                (
                    order_id,
                    user["id"],
                    product["id"],
                    product["product_name"],
                    product["category"],
                    user["city"],
                    amount,
                    status,
                    created_at.isoformat(),
                    refund_amount,
                )
            )

        return rows
