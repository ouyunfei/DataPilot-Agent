import re
import sqlite3


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
        self.sqlite = sqlite3.connect(":memory:", check_same_thread=False)

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
