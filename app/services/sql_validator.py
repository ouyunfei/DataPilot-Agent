from __future__ import annotations

import re

import sqlglot
from sqlglot import exp


class SQLSafetyError(ValueError):
    """Raised when generated SQL violates the read-only query policy."""


FORBIDDEN_KEYWORDS = {
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
ALLOWED_TABLES = {"orders", "users", "products"}
MAX_LIMIT = 100


def validate_select_sql(sql: str, allowed_tables: set[str] | None = None) -> str:
    allowed_tables = ALLOWED_TABLES if allowed_tables is None else allowed_tables
    normalized = sql.strip()
    if not normalized:
        raise SQLSafetyError("SQL 不安全：只允许执行 SELECT 查询")

    if _has_comment(normalized):
        raise SQLSafetyError("SQL 不安全：不允许包含注释")

    if _has_multiple_statements(normalized):
        raise SQLSafetyError("SQL 不安全：不允许多语句 SQL")

    normalized = normalized[:-1].strip() if normalized.endswith(";") else normalized
    without_literals = _replace_string_literals(normalized)

    if not without_literals.lstrip().upper().startswith("SELECT"):
        raise SQLSafetyError("SQL 不安全：只允许执行 SELECT 查询")

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", without_literals, flags=re.IGNORECASE):
            raise SQLSafetyError(f"SQL 不安全：禁止使用 {keyword} 语句")

    try:
        expression = sqlglot.parse_one(normalized, read="sqlite")
    except sqlglot.errors.ParseError as exc:
        raise SQLSafetyError(f"SQL 不安全：SQL 解析失败：{exc}") from exc

    if not isinstance(expression, exp.Select):
        raise SQLSafetyError("SQL 不安全：只允许执行 SELECT 查询")

    if _has_select_star_projection(expression):
        raise SQLSafetyError("SQL 不安全：禁止使用 SELECT *")

    table_names = {table.name.lower() for table in expression.find_all(exp.Table)}
    disallowed_tables = table_names - {table.lower() for table in allowed_tables}
    if disallowed_tables:
        names = "、".join(sorted(disallowed_tables))
        raise SQLSafetyError(f"SQL 不安全：禁止访问非白名单表 {names}")

    expression = _enforce_limit(expression)
    return expression.sql(dialect="sqlite")


def _enforce_limit(expression: exp.Select) -> exp.Select:
    limit = expression.args.get("limit")
    if limit is None:
        return expression.limit(MAX_LIMIT)

    limit_value = _literal_int(limit.expression)
    if limit_value is None or limit_value > MAX_LIMIT:
        expression.set("limit", exp.Limit(expression=exp.Literal.number(MAX_LIMIT)))
    return expression


def _has_select_star_projection(expression: exp.Select) -> bool:
    for projection in expression.expressions:
        if isinstance(projection, exp.Star):
            return True
        if isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
            return True
    return False


def _has_comment(sql: str) -> bool:
    without_literals = _replace_string_literals(sql)
    return "--" in without_literals or "/*" in without_literals or "*/" in without_literals


def _has_multiple_statements(sql: str) -> bool:
    semicolon_positions = _semicolon_positions_outside_literals(sql)
    if not semicolon_positions:
        return False

    last_non_space_index = len(sql.rstrip()) - 1
    return semicolon_positions != [last_non_space_index]


def _semicolon_positions_outside_literals(sql: str) -> list[int]:
    positions: list[int] = []
    quote: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == ";":
            positions.append(index)
        index += 1

    return positions


def _replace_string_literals(sql: str) -> str:
    chars: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    chars.append(" ")
                    chars.append(" ")
                    index += 2
                    continue
                quote = None
            chars.append(" ")
        else:
            if char in {"'", '"'}:
                quote = char
                chars.append(" ")
            else:
                chars.append(char)
        index += 1

    return "".join(chars)


def _literal_int(expression: exp.Expression | None) -> int | None:
    if not isinstance(expression, exp.Literal):
        return None
    try:
        return int(expression.this)
    except (TypeError, ValueError):
        return None
