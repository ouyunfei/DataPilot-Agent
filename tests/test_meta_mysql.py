import re
import sqlite3

import pytest

from app.db.database import DEFAULT_METRICS
from app.db.database import SQLiteDatabase
from app.db.meta_mysql import MySQLMetaDatabase


class FakeMySQLCursor:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._cursor = conn.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._cursor.close()

    def execute(self, sql: str, params=()):
        self._cursor.execute(self._translate(sql), params or ())
        return self

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @staticmethod
    def _translate(sql: str) -> str:
        sql = sql.replace("%s", "?")
        sql = sql.replace("INSERT IGNORE", "INSERT OR IGNORE")
        sql = re.sub(
            r"\bid\s+BIGINT\s+AUTO_INCREMENT\s+PRIMARY\s+KEY\b",
            "id INTEGER PRIMARY KEY AUTOINCREMENT",
            sql,
            flags=re.I,
        )
        sql = re.sub(r"\bBIGINT\b", "INTEGER", sql, flags=re.I)
        sql = re.sub(r"\bINT\b", "INTEGER", sql, flags=re.I)
        sql = re.sub(r"\bTINYINT\(1\)\b", "INTEGER", sql, flags=re.I)
        sql = re.sub(r"\bVARCHAR\(\d+\)\b", "TEXT", sql, flags=re.I)
        sql = re.sub(r"\bDATETIME\b", "TEXT", sql, flags=re.I)
        sql = re.sub(r"\s+ON UPDATE CURRENT_TIMESTAMP", "", sql, flags=re.I)
        return sql


class FakeMySQLConnection:
    def __init__(self) -> None:
        self.sqlite = sqlite3.connect(":memory:")

    def cursor(self):
        return FakeMySQLCursor(self.sqlite)

    def commit(self):
        self.sqlite.commit()

    def rollback(self):
        self.sqlite.rollback()

    def close(self):
        pass

    def table_names(self) -> set[str]:
        rows = self.sqlite.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        return {row[0] for row in rows}


def _db(tmp_path):
    fake = FakeMySQLConnection()
    db = MySQLMetaDatabase(
        "mysql://user:secret@localhost:3306/datapilot",
        tmp_path / "demo.db",
        connect=lambda **_kwargs: fake,
    )
    return db, fake


def test_mysql_meta_database_initializes_platform_tables_and_defaults(tmp_path):
    db, fake = _db(tmp_path)

    db.initialize()

    assert {
        "data_sources",
        "metrics",
        "query_logs",
        "chat_sessions",
        "chat_messages",
    } <= fake.table_names()
    source = db.get_default_data_source()
    assert source["name"] == "default_sqlite"
    assert source["database_url"] == str(tmp_path / "demo.db")
    assert len(db.list_metrics()) == len(DEFAULT_METRICS)


def test_mysql_meta_database_data_source_crud_matches_sqlite_behavior(tmp_path):
    db, _fake = _db(tmp_path)
    db.initialize()

    created = db.create_data_source(
        name="orders_only",
        db_type="sqlite",
        database_url=str(tmp_path / "demo.db"),
        allowed_tables=["orders"],
        allowed_columns={"orders": ["id", "amount"]},
    )
    updated = db.update_data_source(
        created["id"],
        allowed_tables=["products"],
        allowed_columns={"products": ["id", "product_name"]},
        is_default=True,
    )

    assert updated["allowed_tables"] == ["products"]
    assert updated["allowed_columns"] == {"products": ["id", "product_name"]}
    assert db.get_default_data_source()["id"] == created["id"]
    with pytest.raises(ValueError, match="默认数据源"):
        db.delete_data_source(created["id"])


def test_mysql_meta_database_metric_crud_matches_sqlite_behavior(tmp_path):
    db, _fake = _db(tmp_path)
    db.initialize()

    created = db.create_metric(
        metric_key="repeat_order_count",
        name="复购订单数",
        expression="COUNT(orders.id)",
        description="重复购买订单数量。",
    )
    updated = db.update_metric(created["id"], enabled=False)

    assert updated["enabled"] is False
    assert "复购订单数" not in {m["name"] for m in db.list_metrics(enabled_only=True)}
    assert db.delete_metric(created["id"]) is True
    assert db.get_metric(created["id"]) is None


def test_mysql_meta_database_logs_feedback_stats_history_and_sessions(tmp_path):
    db, _fake = _db(tmp_path)
    db.initialize()
    source_id = db.get_default_data_source()["id"]

    db.log_query(
        question="最近 30 天销售额是多少？",
        sql="SELECT SUM(amount) FROM orders",
        trusted_answer=False,
        chart_type="bar",
        row_count=1,
        error=None,
        duration_ms=10,
        data_source_id=source_id,
        sql_explanation="汇总订单金额。",
        answer="销售额 100 万。",
    )
    log_id = db.list_query_logs()[0]["id"]
    db.update_query_feedback(log_id, "like", "准确")
    session_id = db.create_session("s1")
    db.save_chat_message(session_id, "问题", "SELECT 1", "答案")

    history = db.list_high_quality_historical_qa(source_id)
    stats = db.get_query_stats()
    context = db.get_recent_session_context(session_id)

    assert history[0]["id"] == log_id
    assert db.list_query_logs()[0]["feedback"] == "like"
    assert stats["total_queries"] == 1
    assert stats["chart_type_counts"] == {"bar": 1}
    assert "问题" in context


def test_mysql_meta_database_hides_password_in_errors(tmp_path):
    def fail_connect(**_kwargs):
        raise RuntimeError("cannot connect with secret")

    db = MySQLMetaDatabase(
        "mysql://user:secret@localhost:3306/datapilot",
        tmp_path / "demo.db",
        connect=fail_connect,
    )

    with pytest.raises(RuntimeError) as excinfo:
        db.list_metrics()

    assert "secret" not in str(excinfo.value)
    assert "***" in str(excinfo.value)


def test_migration_copies_sqlite_metadata_to_mysql_idempotently(tmp_path):
    from scripts.migrate_sqlite_meta_to_mysql import migrate_metadata

    sqlite_db = SQLiteDatabase(tmp_path / "source.db")
    sqlite_db.initialize()
    source = sqlite_db.get_default_data_source()
    extra_source = sqlite_db.create_data_source(
        name="orders_only",
        db_type="sqlite",
        database_url=str(tmp_path / "source.db"),
        allowed_tables=["orders"],
    )
    metric = sqlite_db.create_metric(
        metric_key="repeat_order_count",
        name="复购订单数",
        expression="COUNT(orders.id)",
        description="重复购买订单数量。",
    )
    sqlite_db.log_query(
        question="最近 30 天销售额是多少？",
        sql="SELECT SUM(amount) FROM orders",
        trusted_answer=False,
        chart_type="bar",
        row_count=1,
        error=None,
        duration_ms=10,
        data_source_id=source["id"],
        sql_explanation="汇总订单金额。",
        answer="销售额 100 万。",
    )
    log_id = sqlite_db.list_query_logs()[0]["id"]
    sqlite_db.update_query_feedback(log_id, "like", "准确")
    sqlite_db.create_session("s1")
    sqlite_db.save_chat_message("s1", "问题", "SELECT 1", "答案")

    target, fake = _db(tmp_path)

    first = migrate_metadata(sqlite_db.path, target)
    second = migrate_metadata(sqlite_db.path, target)

    assert first == second
    assert first["data_sources"] == len(sqlite_db.list_data_sources())
    assert first["metrics"] == len(sqlite_db.list_metrics())
    assert target.get_data_source(extra_source["id"])["name"] == "orders_only"
    assert target.get_metric(metric["id"])["name"] == "复购订单数"
    assert target.list_high_quality_historical_qa(source["id"])[0]["id"] == log_id
    assert "问题" in target.get_recent_session_context("s1")
    assert fake.sqlite.execute("SELECT COUNT(*) FROM data_sources").fetchone()[0] == first["data_sources"]

    with sqlite_db._connect() as conn:
        source_created_at = conn.execute(
            "SELECT created_at FROM query_logs WHERE id = ?",
            (log_id,),
        ).fetchone()["created_at"]
    target_created_at = fake.sqlite.execute(
        "SELECT created_at FROM query_logs WHERE id = ?",
        (log_id,),
    ).fetchone()[0]
    assert target_created_at == source_created_at
