from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from app.core.config import DEFAULT_DATABASE_PATH, META_DATABASE_URL
from app.db.meta_mysql import MySQLMetaDatabase


TABLE_COLUMNS = {
    "data_sources": (
        "id",
        "name",
        "db_type",
        "database_url",
        "allowed_tables",
        "allowed_columns",
        "is_default",
        "created_at",
    ),
    "metrics": (
        "id",
        "metric_key",
        "name",
        "expression",
        "description",
        "enabled",
        "created_at",
        "updated_at",
    ),
    "query_logs": (
        "id",
        "question",
        "sql",
        "trusted_answer",
        "chart_type",
        "row_count",
        "error",
        "error_code",
        "feedback",
        "feedback_note",
        "duration_ms",
        "data_source_id",
        "sql_explanation",
        "answer",
        "created_at",
    ),
    "chat_sessions": ("id", "created_at", "updated_at"),
    "chat_messages": ("id", "session_id", "question", "sql", "answer", "created_at"),
}


def migrate_metadata(
    sqlite_path: str | Path,
    target: MySQLMetaDatabase,
) -> dict[str, int]:
    target.initialize()
    counts: dict[str, int] = {}
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        for table, columns in TABLE_COLUMNS.items():
            rows = conn.execute(
                f"SELECT {', '.join(columns)} FROM {table} ORDER BY {columns[0]}"
            ).fetchall()
            for row in rows:
                _replace_row(target, table, columns, row)
            counts[table] = len(rows)
    return counts


def _replace_row(
    target: MySQLMetaDatabase,
    table: str,
    columns: tuple[str, ...],
    row: sqlite3.Row,
) -> None:
    placeholders = ", ".join(["%s"] * len(columns))
    target._execute(
        f"REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(row[column] for column in columns),
    )


def _sanitize(message: str, database_url: str) -> str:
    password = urlsplit(database_url).password or ""
    if not password:
        return message
    return message.replace(password, "***").replace(quote(password, safe=""), "***")


def main() -> int:
    try:
        if not META_DATABASE_URL:
            raise ValueError("请先配置 META_DATABASE_URL")
        counts = migrate_metadata(
            DEFAULT_DATABASE_PATH,
            MySQLMetaDatabase(META_DATABASE_URL, DEFAULT_DATABASE_PATH),
        )
    except Exception as exc:
        print(
            f"迁移失败：{_sanitize(str(exc), META_DATABASE_URL)}",
            file=sys.stderr,
        )
        return 1

    for table in TABLE_COLUMNS:
        print(f"{table}: {counts[table]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
