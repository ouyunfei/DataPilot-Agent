from __future__ import annotations

import random
import sqlite3
import uuid
import json
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator


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

    def get_schema_description(self, allowed_tables: list[str] | None = None) -> str:
        table_descriptions = {
            "orders": ("订单事实表", ORDER_FIELD_DESCRIPTIONS),
            "users": ("用户维度表", USER_FIELD_DESCRIPTIONS),
            "products": ("商品维度表", PRODUCT_FIELD_DESCRIPTIONS),
        }
        selected_tables = set(allowed_tables or table_descriptions.keys())
        lines = [f"当前允许查询的业务表：{'、'.join(sorted(selected_tables))}。"]
        if {"orders", "users"} <= selected_tables:
            lines.append("表关系：orders.user_id = users.id。")
        if {"orders", "products"} <= selected_tables:
            lines.append("表关系：orders.product_id = products.id。")

        with self._connect() as conn:
            for table_name, (table_comment, field_descriptions) in table_descriptions.items():
                if table_name not in selected_tables:
                    continue
                columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
                lines.append("")
                lines.append(f"表：{table_name}（{table_comment}）")
                lines.append("字段：")
                for column in columns:
                    name = column["name"]
                    column_type = column["type"]
                    description = field_descriptions.get(name, "")
                    if name == "user_id" and "users" not in selected_tables:
                        description = "用户 ID"
                    if name == "product_id" and "products" not in selected_tables:
                        description = "商品 ID"
                    lines.append(f"- {name} ({column_type})：{description}")

        return "\n".join(lines)

    def list_tables(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
            return [row["name"] for row in rows]

    def execute_select(self, sql: str, database_url: str | None = None) -> list[dict[str, Any]]:
        with self._connect(database_url) as conn:
            cursor = conn.execute(sql)
            return [dict(row) for row in cursor.fetchall()]

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
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

    def create_data_source(
        self,
        name: str,
        db_type: str,
        database_url: str,
        allowed_tables: list[str],
        is_default: bool = False,
    ) -> dict[str, Any]:
        db_type = db_type.lower()
        if db_type not in {"sqlite", "mysql", "postgresql"}:
            raise ValueError("db_type 只支持 sqlite、mysql、postgresql")

        tables = [table.strip().lower() for table in allowed_tables if table.strip()]
        if not tables:
            raise ValueError("allowed_tables 不能为空")

        with self._connect() as conn:
            if is_default:
                conn.execute("UPDATE data_sources SET is_default = 0")
            cursor = conn.execute(
                """
                INSERT INTO data_sources (name, db_type, database_url, allowed_tables, is_default)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, db_type, database_url, json.dumps(tables, ensure_ascii=False), int(is_default)),
            )
            source_id = cursor.lastrowid

        source = self.get_data_source(source_id)
        if source is None:
            raise ValueError("数据源创建失败")
        return source

    def list_data_sources(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, db_type, database_url, allowed_tables, is_default, created_at
                FROM data_sources
                ORDER BY is_default DESC, id ASC
                """
            ).fetchall()
            return [self._data_source_from_row(row) for row in rows]

    def get_data_source(self, source_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, db_type, database_url, allowed_tables, is_default, created_at
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
                SELECT id, name, db_type, database_url, allowed_tables, is_default, created_at
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

    @staticmethod
    def _data_source_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "db_type": row["db_type"],
            "database_url": row["database_url"],
            "allowed_tables": json.loads(row["allowed_tables"]),
            "is_default": bool(row["is_default"]),
            "created_at": row["created_at"],
        }

    def log_query(
        self,
        question: str,
        sql: str,
        trusted_answer: bool,
        chart_type: str,
        row_count: int,
        error: str | None,
        duration_ms: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO query_logs (
                    question, sql, trusted_answer, chart_type, row_count, error, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (question, sql, int(trusted_answer), chart_type, row_count, error, duration_ms),
            )

    def list_query_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, question, sql, trusted_answer, chart_type, row_count,
                    error, feedback, feedback_note, duration_ms, created_at
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

        return {
            "total_queries": summary["total_queries"] or 0,
            "success_queries": summary["success_queries"] or 0,
            "failed_queries": summary["failed_queries"] or 0,
            "trusted_answer_queries": summary["trusted_answer_queries"] or 0,
            "average_duration_ms": summary["average_duration_ms"] or 0,
            "chart_type_counts": {row["chart_type"]: row["count"] for row in chart_rows},
            "feedback_counts": {row["feedback"]: row["count"] for row in feedback_rows},
            "top_questions": [dict(row) for row in question_rows],
        }

    def _seed_if_empty(self, conn: sqlite3.Connection) -> None:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

        if user_count == 0:
            conn.executemany(
                """
                INSERT INTO users (id, name, city, level, registered_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                self._build_seed_users(),
            )
        if product_count == 0:
            conn.executemany(
                """
                INSERT INTO products (id, product_name, category, brand, cost_price, list_price)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                self._build_seed_products(),
            )
        if order_count == 0:
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
                """,
                self._build_seed_orders(products=products, users=users),
            )

    @staticmethod
    def _build_seed_users() -> list[tuple[Any, ...]]:
        cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京"]
        levels = ["普通", "银卡", "金卡", "黑金"]
        today = date.today()
        rows: list[tuple[Any, ...]] = []
        for index in range(1, 25):
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
        ]

    @staticmethod
    def _build_seed_orders(
        products: list[sqlite3.Row],
        users: list[sqlite3.Row],
    ) -> list[tuple[Any, ...]]:
        random.seed(202409)
        today = date.today()
        rows: list[tuple[Any, ...]] = []

        for order_id in range(1, 181):
            product = products[order_id % len(products)]
            user = users[order_id % len(users)]
            created_at = today - timedelta(days=order_id % 60)
            status = "paid"
            refund_amount = 0.0
            if order_id % 17 == 0:
                status = "refunded"
                refund_amount = float(product["list_price"])
            elif order_id % 29 == 0:
                status = "cancelled"

            amount = round(float(product["list_price"]) * random.uniform(0.85, 1.25), 2)
            if status == "cancelled":
                amount = 0.0
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
