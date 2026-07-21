from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Callable, Iterator

from app.core.config import DEFAULT_MYSQL_DATA_SOURCE_URL
from app.db.database import DEFAULT_METRICS, DataPilotDatabase, SUPPORTED_DATA_SOURCE_TYPES
from app.db.mysql import MySQLClient


DEFAULT_MYSQL_DATA_SOURCE_NAME = "default_mysql"
DEFAULT_MYSQL_DATA_SOURCE_TABLES = ["orders", "users", "products"]


class MySQLMetaDatabase(DataPilotDatabase):
    """MySQL-backed platform metadata and default business data-source config."""

    def __init__(
        self,
        database_url: str,
        connect: Callable[..., Any] | None = None,
    ) -> None:
        self.database_url = database_url
        self._client = MySQLClient(database_url, connect=connect)

    def initialize(self) -> None:
        self._create_meta_tables()
        self._seed_mysql_default_data_source()
        self._execute("DELETE FROM data_sources WHERE db_type = %s", ("sqlite",))
        self._seed_mysql_default_metrics()

    def _create_meta_tables(self) -> None:
        for sql in (
            """
            CREATE TABLE IF NOT EXISTS data_sources (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                db_type VARCHAR(32) NOT NULL,
                database_url TEXT NOT NULL,
                allowed_tables TEXT NOT NULL,
                allowed_columns TEXT,
                is_default TINYINT(1) NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS metrics (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                metric_key VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(100) NOT NULL,
                expression TEXT NOT NULL,
                description TEXT NOT NULL,
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS query_logs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                question TEXT NOT NULL,
                `sql` TEXT NOT NULL,
                trusted_answer TINYINT(1) NOT NULL,
                chart_type VARCHAR(32) NOT NULL,
                row_count INT NOT NULL,
                error TEXT,
                error_code VARCHAR(64),
                feedback VARCHAR(16),
                feedback_note TEXT,
                duration_ms INT NOT NULL,
                data_source_id BIGINT,
                sql_explanation TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id VARCHAR(64) PRIMARY KEY,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(64) NOT NULL,
                question TEXT NOT NULL,
                `sql` TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ):
            self._execute(sql)

    def _seed_mysql_default_data_source(self) -> None:
        tables = DEFAULT_MYSQL_DATA_SOURCE_TABLES
        allowed_columns = DataPilotDatabase._default_allowed_columns(tables)
        default_row = self._fetchone(
            """
            SELECT
                id, name, db_type, database_url, allowed_tables,
                allowed_columns
            FROM data_sources
            WHERE is_default = 1
            ORDER BY id ASC
            LIMIT 1
            """
        )
        mysql_row = self._fetchone(
            """
            SELECT
                id, name, db_type, database_url, allowed_tables,
                allowed_columns
            FROM data_sources
            WHERE name = %s
            ORDER BY is_default DESC, id ASC
            LIMIT 1
            """,
            (DEFAULT_MYSQL_DATA_SOURCE_NAME,),
        )
        if mysql_row is not None:
            current_tables = json.loads(mysql_row["allowed_tables"])
            current_allowed_columns = (
                json.loads(mysql_row["allowed_columns"])
                if mysql_row["allowed_columns"]
                else DataPilotDatabase._default_allowed_columns(current_tables)
            )
            if (
                mysql_row["db_type"] == "mysql"
                and mysql_row["database_url"] == DEFAULT_MYSQL_DATA_SOURCE_URL
                and current_tables == tables
                and current_allowed_columns == allowed_columns
            ):
                if default_row is not None and default_row["id"] != mysql_row["id"]:
                    self._execute(
                        "UPDATE data_sources SET is_default = 0 WHERE id = %s",
                        (default_row["id"],),
                    )
                    self._execute(
                        "UPDATE data_sources SET is_default = 1 WHERE id = %s",
                        (mysql_row["id"],),
                    )
                return
            self._execute(
                """
                UPDATE data_sources
                SET db_type = %s,
                    database_url = %s,
                    allowed_tables = %s,
                    allowed_columns = %s,
                    is_default = 1
                WHERE id = %s
                """,
                (
                    "mysql",
                    DEFAULT_MYSQL_DATA_SOURCE_URL,
                    json.dumps(tables, ensure_ascii=False),
                    json.dumps(allowed_columns, ensure_ascii=False),
                    mysql_row["id"],
                ),
            )
            if default_row is not None and default_row["id"] != mysql_row["id"]:
                self._execute(
                    "UPDATE data_sources SET is_default = 0 WHERE id = %s",
                    (default_row["id"],),
                )
            return
        if default_row is not None:
            current_tables = json.loads(default_row["allowed_tables"])
            current_allowed_columns = (
                json.loads(default_row["allowed_columns"])
                if default_row["allowed_columns"]
                else DataPilotDatabase._default_allowed_columns(current_tables)
            )
            if (
                default_row["name"] == DEFAULT_MYSQL_DATA_SOURCE_NAME
                and default_row["db_type"] == "mysql"
                and default_row["database_url"] == DEFAULT_MYSQL_DATA_SOURCE_URL
                and current_tables == tables
                and current_allowed_columns == allowed_columns
            ):
                return
            self._execute(
                """
                UPDATE data_sources
                SET name = %s,
                    db_type = %s,
                    database_url = %s,
                    allowed_tables = %s,
                    allowed_columns = %s,
                    is_default = 1
                WHERE id = %s
                """,
                (
                    DEFAULT_MYSQL_DATA_SOURCE_NAME,
                    "mysql",
                    DEFAULT_MYSQL_DATA_SOURCE_URL,
                    json.dumps(tables, ensure_ascii=False),
                    json.dumps(allowed_columns, ensure_ascii=False),
                    default_row["id"],
                ),
            )
            return
        self._execute(
            """
            INSERT INTO data_sources (
                name, db_type, database_url, allowed_tables, allowed_columns, is_default
            )
            VALUES (%s, %s, %s, %s, %s, 1)
            """,
            (
                DEFAULT_MYSQL_DATA_SOURCE_NAME,
                "mysql",
                DEFAULT_MYSQL_DATA_SOURCE_URL,
                json.dumps(tables, ensure_ascii=False),
                json.dumps(allowed_columns, ensure_ascii=False),
            ),
        )

    def _seed_mysql_default_metrics(self) -> None:
        for metric in DEFAULT_METRICS:
            self._execute(
                """
                INSERT IGNORE INTO metrics (
                    metric_key, name, expression, description, enabled
                )
                VALUES (%s, %s, %s, %s, 1)
                """,
                (
                    metric["metric_key"],
                    metric["name"],
                    metric["expression"],
                    metric["description"],
                ),
            )

    def list_metrics(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE enabled = 1" if enabled_only else ""
        return [
            self._metric_from_row(row)
            for row in self._fetchall(
                f"""
                SELECT
                    id, metric_key, name, expression, description,
                    enabled, created_at, updated_at
                FROM metrics
                {where}
                ORDER BY id ASC
                """
            )
        ]

    def get_metric(self, metric_id: int) -> dict[str, Any] | None:
        row = self._fetchone(
            """
            SELECT
                id, metric_key, name, expression, description,
                enabled, created_at, updated_at
            FROM metrics
            WHERE id = %s
            """,
            (metric_id,),
        )
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
        metric_id = self._execute(
            """
            INSERT INTO metrics (metric_key, name, expression, description, enabled)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (metric_key, name, expression, description, int(enabled)),
        )
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
            "metric_key": metric_key.strip().lower() if metric_key is not None else current["metric_key"],
            "name": name.strip() if name is not None else current["name"],
            "expression": expression.strip() if expression is not None else current["expression"],
            "description": description.strip() if description is not None else current["description"],
            "enabled": current["enabled"] if enabled is None else enabled,
        }
        self._validate_metric(
            next_metric["metric_key"],
            next_metric["name"],
            next_metric["expression"],
            next_metric["description"],
        )
        self._execute(
            """
            UPDATE metrics
            SET
                metric_key = %s,
                name = %s,
                expression = %s,
                description = %s,
                enabled = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
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
        return self._execute("DELETE FROM metrics WHERE id = %s", (metric_id,), rowcount=True) > 0

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
        if db_type not in SUPPORTED_DATA_SOURCE_TYPES:
            raise ValueError("db_type 只支持 mysql、postgresql")
        tables = [table.strip().lower() for table in allowed_tables if table.strip()]
        if not tables:
            raise ValueError("allowed_tables 不能为空")
        if db_type == "mysql" and (
            not allowed_columns
            or any(not any(c.strip() for c in allowed_columns.get(t, [])) for t in tables)
        ):
            raise ValueError("MySQL 数据源必须为每个白名单表显式配置 allowed_columns")
        columns = self._normalize_allowed_columns(tables, allowed_columns)
        if is_default:
            self._execute("UPDATE data_sources SET is_default = 0")
        source_id = self._execute(
            """
            INSERT INTO data_sources (
                name, db_type, database_url, allowed_tables, allowed_columns, is_default
            )
            VALUES (%s, %s, %s, %s, %s, %s)
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
        current = self.get_data_source(source_id)
        if current is None:
            return None
        next_database_url = database_url if database_url is not None else current["database_url"]
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
            or any(not any(c.strip() for c in columns_input.get(t, [])) for t in tables)
        ):
            raise ValueError("MySQL 数据源必须为每个白名单表显式配置 allowed_columns")
        columns = self._normalize_allowed_columns(tables, columns_input)
        if current["is_default"] and is_default is False:
            raise ValueError("默认数据源不能取消默认状态，请先设置其他默认数据源")
        next_is_default = current["is_default"] if is_default is None else is_default
        if is_default is True and not current["is_default"]:
            self._execute("UPDATE data_sources SET is_default = 0")
        self._execute(
            """
            UPDATE data_sources
            SET database_url = %s, allowed_tables = %s, allowed_columns = %s, is_default = %s
            WHERE id = %s
            """,
            (
                next_database_url,
                json.dumps(tables, ensure_ascii=False),
                json.dumps(columns, ensure_ascii=False),
                int(next_is_default),
                source_id,
            ),
        )
        return self.get_data_source(source_id)

    def delete_data_source(self, source_id: int) -> bool:
        source = self.get_data_source(source_id)
        if source is None:
            return False
        if source["is_default"]:
            raise ValueError("默认数据源不能删除，请先设置其他默认数据源")
        return self._execute(
            "DELETE FROM data_sources WHERE id = %s",
            (source_id,),
            rowcount=True,
        ) > 0

    def list_data_sources(self) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT
                id, name, db_type, database_url, allowed_tables,
                allowed_columns, is_default, created_at
            FROM data_sources
            ORDER BY is_default DESC, id ASC
            """
        )
        return [self._data_source_from_row(row) for row in rows]

    def get_data_source(self, source_id: int) -> dict[str, Any] | None:
        row = self._fetchone(
            """
            SELECT
                id, name, db_type, database_url, allowed_tables,
                allowed_columns, is_default, created_at
            FROM data_sources
            WHERE id = %s
            """,
            (source_id,),
        )
        return self._data_source_from_row(row) if row else None

    def get_default_data_source(self) -> dict[str, Any]:
        row = self._fetchone(
            """
            SELECT
                id, name, db_type, database_url, allowed_tables,
                allowed_columns, is_default, created_at
            FROM data_sources
            WHERE is_default = 1
            ORDER BY id ASC
            LIMIT 1
            """
        )
        if row is None:
            raise ValueError("默认数据源不存在")
        return self._data_source_from_row(row)

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
        data_source_id: int | None = None,
        sql_explanation: str = "",
        answer: str = "",
    ) -> None:
        self._execute(
            """
            INSERT INTO query_logs (
                question, `sql`, trusted_answer, chart_type, row_count,
                error, error_code, duration_ms, data_source_id,
                sql_explanation, answer
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                data_source_id,
                sql_explanation,
                answer,
            ),
        )

    def list_query_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._fetchall(
            """
            SELECT
                id, question, `sql`, trusted_answer, chart_type, row_count,
                error, error_code, feedback, feedback_note, duration_ms, created_at
            FROM query_logs
            ORDER BY id DESC
            LIMIT %s
            """,
            (max(1, min(limit, 100)),),
        )

    def update_query_feedback(
        self, log_id: int, feedback: str, note: str | None = None
    ) -> bool:
        return self._execute(
            """
            UPDATE query_logs
            SET feedback = %s, feedback_note = %s
            WHERE id = %s
            """,
            (feedback, note, log_id),
            rowcount=True,
        ) > 0

    def list_high_quality_historical_qa(
        self, data_source_id: int
    ) -> list[dict[str, Any]]:
        return self._fetchall(
            """
            SELECT id, question, `sql`, sql_explanation, answer, data_source_id
            FROM query_logs
            WHERE data_source_id = %s
              AND error IS NULL
              AND feedback = 'like'
              AND TRIM(question) != ''
              AND TRIM(`sql`) != ''
              AND TRIM(answer) != ''
            ORDER BY id ASC
            """,
            (data_source_id,),
        )

    def create_session(self, session_id: str | None = None) -> str:
        session_id = session_id or str(uuid.uuid4())
        self._execute("INSERT IGNORE INTO chat_sessions (id) VALUES (%s)", (session_id,))
        self._execute(
            "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (session_id,),
        )
        return session_id

    def save_chat_message(self, session_id: str, question: str, sql: str, answer: str) -> None:
        self._execute(
            """
            INSERT INTO chat_messages (session_id, question, `sql`, answer)
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, question, sql, answer),
        )
        self._execute(
            "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (session_id,),
        )

    def get_recent_session_context(self, session_id: str, limit: int = 3) -> str:
        rows = self._fetchall(
            """
            SELECT question, `sql`, answer
            FROM chat_messages
            WHERE session_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (session_id, max(1, min(limit, 10))),
        )
        if not rows:
            return ""
        lines = ["最近会话上下文："]
        for row in reversed(rows):
            lines.append(f"- 用户问题：{row['question']}")
            lines.append(f"  SQL：{row['sql']}")
            lines.append(f"  回答：{row['answer']}")
        return "\n".join(lines)

    def get_query_stats(self) -> dict[str, Any]:
        summary = self._fetchone(
            """
            SELECT
                COUNT(*) AS total_queries,
                SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS success_queries,
                SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS failed_queries,
                SUM(trusted_answer) AS trusted_answer_queries,
                COALESCE(ROUND(AVG(duration_ms), 2), 0) AS average_duration_ms
            FROM query_logs
            """
        )
        chart_rows = self._fetchall(
            """
            SELECT chart_type, COUNT(*) AS count
            FROM query_logs
            WHERE chart_type != ''
            GROUP BY chart_type
            ORDER BY count DESC
            """
        )
        feedback_rows = self._fetchall(
            """
            SELECT feedback, COUNT(*) AS count
            FROM query_logs
            WHERE feedback IS NOT NULL
            GROUP BY feedback
            ORDER BY count DESC
            """
        )
        question_rows = self._fetchall(
            """
            SELECT question, COUNT(*) AS count
            FROM query_logs
            GROUP BY question
            ORDER BY count DESC, question ASC
            LIMIT 5
            """
        )
        error_code_rows = self._fetchall(
            """
            SELECT error_code, COUNT(*) AS count
            FROM query_logs
            WHERE error_code IS NOT NULL
            GROUP BY error_code
            ORDER BY count DESC
            """
        )
        summary = summary or {}
        return {
            "total_queries": summary.get("total_queries") or 0,
            "success_queries": summary.get("success_queries") or 0,
            "failed_queries": summary.get("failed_queries") or 0,
            "trusted_answer_queries": summary.get("trusted_answer_queries") or 0,
            "average_duration_ms": summary.get("average_duration_ms") or 0,
            "chart_type_counts": {row["chart_type"]: row["count"] for row in chart_rows},
            "feedback_counts": {row["feedback"]: row["count"] for row in feedback_rows},
            "error_code_counts": {row["error_code"]: row["count"] for row in error_code_rows},
            "top_questions": question_rows,
        }

    def _execute(self, sql: str, params: tuple[Any, ...] = (), rowcount: bool = False) -> int:
        try:
            with self._mysql_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    return cursor.rowcount if rowcount else (cursor.lastrowid or 0)
        except Exception as exc:
            raise RuntimeError(self._client._sanitize(str(exc))) from exc

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self._fetchall(sql, params)
        return rows[0] if rows else None

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        try:
            with self._mysql_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    columns = [MySQLClient._column_name(c) for c in (cursor.description or [])]
                    return [self._row_dict(columns, row) for row in cursor.fetchall()]
        except Exception as exc:
            raise RuntimeError(self._client._sanitize(str(exc))) from exc

    @contextmanager
    def _mysql_connection(self) -> Iterator[Any]:
        conn = self._client._connection()
        try:
            yield conn
            if hasattr(conn, "commit"):
                conn.commit()
        except Exception:
            if hasattr(conn, "rollback"):
                conn.rollback()
            raise
        finally:
            if hasattr(conn, "close"):
                conn.close()

    @staticmethod
    def _row_dict(columns: list[str], row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            items = row.items()
        else:
            items = zip(columns, row)
        return {key: MySQLMetaDatabase._value(value) for key, value in items}

    @staticmethod
    def _value(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        if isinstance(value, date):
            return value.isoformat()
        return value
