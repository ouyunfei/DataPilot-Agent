from __future__ import annotations

from pathlib import Path

from app.db.database import SQLiteDatabase


class MySQLMetaDatabase(SQLiteDatabase):
    def __init__(self, database_url: str, sqlite_path: str | Path) -> None:
        super().__init__(sqlite_path)
        self.database_url = database_url

