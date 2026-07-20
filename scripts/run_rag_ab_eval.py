from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import sqlglot
from qdrant_client import QdrantClient, models
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.workflow import DataAnalysisAgent
from app.core.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT_SECONDS,
    DEFAULT_DATABASE_PATH,
    EMBEDDING_MODEL,
    KNOWLEDGE_TOP_K,
    QDRANT_COLLECTION,
    QDRANT_PATH,
)
from app.db.database import SQLiteDatabase
from app.services.knowledge import (
    BGEEmbedder,
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL_NAME,
    QdrantKnowledgeBase,
)
from app.services.llm import BaseLLMClient, DeepSeekLLMClient, SQLGeneration


FIXED_ANALYSIS = "Real DeepSeek RAG A/B only scores SQL generation and execution."

CASES = [
    {
        "id": "paid_sales_30_day_ranking",
        "question": "请列出过去30天实际成交销售额最高的5个商品。",
        "required_tables": {"orders"},
        "required_columns": {"product_name", "amount", "status", "created_at"},
        "required_literals": {"paid", "-30 days"},
        "require_select": True,
        "require_group_by": True,
        "require_desc_order": True,
        "require_aggregate": True,
        "require_where": True,
        "require_paid_where": True,
        "require_date_where": True,
        "require_orders_products_join": False,
        "require_sum_amount": True,
        "require_aggregate_subtraction": False,
        "require_ratio": False,
        "require_refund_condition": False,
        "required_group_columns": {"product_name"},
        "max_limit": 5,
    },
    {
        "id": "gross_profit_by_brand",
        "question": "按品牌比较已成交订单的毛利，列出最高的5个品牌。",
        "required_tables": {"orders", "products"},
        "required_columns": {
            "brand",
            "amount",
            "cost_price",
            "product_id",
            "id",
            "status",
        },
        "required_literals": {"paid"},
        "require_select": True,
        "require_group_by": True,
        "require_desc_order": True,
        "require_aggregate": True,
        "require_where": True,
        "require_paid_where": True,
        "require_date_where": False,
        "require_orders_products_join": True,
        "require_sum_amount": False,
        "require_aggregate_subtraction": True,
        "require_ratio": False,
        "require_refund_condition": False,
        "required_group_columns": {"brand"},
        "max_limit": 5,
    },
    {
        "id": "category_refund_rate",
        "question": "想看各商品品类的退款占比排行，退款应按发生退款的订单来认定。",
        "required_tables": {"orders"},
        "required_columns": {"category", "refund_amount", "status"},
        "required_literals": {"refunded", "0"},
        "require_select": True,
        "require_group_by": True,
        "require_desc_order": True,
        "require_aggregate": True,
        "require_where": False,
        "require_paid_where": False,
        "require_date_where": False,
        "require_orders_products_join": False,
        "require_sum_amount": False,
        "require_aggregate_subtraction": False,
        "require_ratio": True,
        "require_refund_condition": True,
        "required_group_columns": {"category"},
        "max_limit": 5,
    },
]


class SQLOnlyLLMClient:
    def __init__(self, delegate: BaseLLMClient) -> None:
        self.delegate = delegate

    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        return self.delegate.generate_sql(question, schema)

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict[str, Any]],
    ) -> str:
        return FIXED_ANALYSIS


def _case_failures(
    case: dict[str, Any], result: dict[str, Any], require_knowledge: bool
) -> list[str]:
    failures = []
    if result.get("error"):
        failures.append("agent error")
    if not result.get("data"):
        failures.append("query returned no data")

    expression = _parse_sql(result.get("sql", ""))
    tables, columns, literals = _sql_terms(expression)
    for label, required, actual in (
        ("tables", case["required_tables"], tables),
        ("columns", case["required_columns"], columns),
        ("literals", case["required_literals"], literals),
    ):
        missing = sorted(required - actual)
        if missing:
            failures.append(f"missing {label}: {', '.join(missing)}")

    failures.extend(_structural_failures(case, expression))

    if require_knowledge and not result.get("knowledge_sources"):
        failures.append("knowledge was not retrieved")
    return failures


def _parse_sql(sql: str) -> exp.Expression | None:
    try:
        return sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.SqlglotError:
        return None


def _sql_terms(
    expression: exp.Expression | None,
) -> tuple[set[str], set[str], set[str]]:
    if expression is None:
        return set(), set(), set()
    return (
        {table.name.lower() for table in expression.find_all(exp.Table)},
        {column.name.lower() for column in expression.find_all(exp.Column)},
        {str(literal.this).lower() for literal in expression.find_all(exp.Literal)},
    )


def _structural_failures(
    case: dict[str, Any], expression: exp.Expression | None
) -> list[str]:
    if expression is None:
        return ["SQL could not be parsed"] if case.get("require_select") else []

    failures = []
    if case.get("require_select") and not isinstance(expression, exp.Select):
        failures.append("query is not a SELECT")
        return failures

    group = expression.args.get("group")
    order = expression.args.get("order")
    aggregates = list(expression.find_all(exp.AggFunc))
    if case.get("require_group_by") and not (group and group.expressions):
        failures.append("query is not grouped")
    if case.get("require_desc_order") and not (
        order and any(item.args.get("desc") is True for item in order.expressions)
    ):
        failures.append("query has no descending order")
    if case.get("require_aggregate") and not aggregates:
        failures.append("query has no aggregate expression")
    if case.get("require_where") and not expression.args.get("where"):
        failures.append("query has no WHERE clause")

    where = expression.args.get("where")
    if case.get("require_paid_where") and not _contains_terms(
        where, columns={"status"}, literals={"paid"}
    ):
        failures.append("WHERE status = paid is required")
    if case.get("require_date_where") and not _contains_terms(
        where, columns={"created_at"}, literals={"-30 days"}
    ):
        failures.append("30-day date filter is required")

    required_group_columns = case.get("required_group_columns", set())
    group_columns = _column_names(group)
    missing_group_columns = sorted(required_group_columns - group_columns)
    if missing_group_columns:
        failures.append(f"query must group by: {', '.join(missing_group_columns)}")

    max_limit = case.get("max_limit")
    if max_limit is not None and _literal_limit(expression) not in range(1, max_limit + 1):
        failures.append(f"LIMIT must be <= {max_limit}")

    if case.get("require_sum_amount") and not any(
        isinstance(aggregate, exp.Sum) and "amount" in _column_names(aggregate)
        for aggregate in aggregates
    ):
        failures.append("SUM(amount) is required")
    if case.get("require_orders_products_join") and not _has_orders_products_join(
        expression
    ):
        failures.append("orders/products join relationship is required")
    if case.get("require_aggregate_subtraction") and not any(
        "amount" in _column_names(subtraction.left)
        and "cost_price" in _column_names(subtraction.right)
        for aggregate in aggregates
        for subtraction in aggregate.find_all(exp.Sub)
    ):
        failures.append("aggregated amount - cost_price is required")
    if case.get("require_ratio") and not any(
        _has_aggregate(division.left) and _has_aggregate(division.right)
        for division in expression.find_all(exp.Div)
    ):
        failures.append("aggregate ratio expression is required")
    if case.get("require_refund_condition") and not _has_refund_condition(
        expression, aggregates
    ):
        failures.append("conditional refund logic inside an aggregate is required")
    return failures


def _column_names(expression: exp.Expression | None) -> set[str]:
    if expression is None:
        return set()
    return {column.name.lower() for column in expression.find_all(exp.Column)}


def _literal_values(expression: exp.Expression | None) -> set[str]:
    if expression is None:
        return set()
    return {
        str(literal.this).lower() for literal in expression.find_all(exp.Literal)
    }


def _contains_terms(
    expression: exp.Expression | None, columns: set[str], literals: set[str]
) -> bool:
    return columns <= _column_names(expression) and literals <= _literal_values(expression)


def _literal_limit(expression: exp.Expression) -> int | None:
    limit = expression.args.get("limit")
    literal = limit.expression if limit else None
    if not isinstance(literal, exp.Literal) or literal.is_string:
        return None
    try:
        return int(literal.this)
    except (TypeError, ValueError):
        return None


def _has_aggregate(expression: exp.Expression) -> bool:
    return isinstance(expression, exp.AggFunc) or any(
        expression.find_all(exp.AggFunc)
    )


def _has_orders_products_join(expression: exp.Expression) -> bool:
    aliases = {
        table.alias_or_name.lower(): table.name.lower()
        for table in expression.find_all(exp.Table)
    }
    required = {("orders", "product_id"), ("products", "id")}
    for join in expression.args.get("joins", []):
        on = join.args.get("on")
        for equality in on.find_all(exp.EQ) if on else []:
            left = _column_references(equality.left, aliases)
            right = _column_references(equality.right, aliases)
            if any({left_ref, right_ref} == required for left_ref in left for right_ref in right):
                return True
    return False


def _column_references(
    expression: exp.Expression, aliases: dict[str, str]
) -> set[tuple[str, str]]:
    return {
        (aliases.get(column.table.lower(), column.table.lower()), column.name.lower())
        for column in expression.find_all(exp.Column)
        if column.table
    }


def _has_refund_condition(
    expression: exp.Expression, aggregates: list[exp.AggFunc]
) -> bool:
    required_columns = {"refund_amount", "status"}
    for aggregate in aggregates:
        for condition in aggregate.find_all(exp.Case, exp.If, exp.Or):
            if required_columns <= _column_names(condition):
                return True
    return any(
        required_columns <= _column_names(filter_expression)
        and _has_aggregate(filter_expression)
        for filter_expression in expression.find_all(exp.Filter)
    )


def _precondition_error() -> str | None:
    if DEEPSEEK_API_KEY.strip().lower() in {
        "",
        "your_deepseek_api_key",
        "placeholder",
        "changeme",
    }:
        return "DeepSeek API key is not configured."
    if EMBEDDING_MODEL != EMBEDDING_MODEL_NAME:
        return "Embedding model does not match the Qdrant Collection."
    if not DEFAULT_DATABASE_PATH.is_file():
        return "Default database is unavailable."
    try:
        source = SQLiteDatabase(DEFAULT_DATABASE_PATH).get_data_source(1)
    except Exception:
        return "Default database is unavailable."
    if not source or source["db_type"] != "sqlite" or not source["is_default"]:
        return "Default data source 1 is unavailable."
    if not QDRANT_PATH.is_dir():
        return "Qdrant path is unavailable."

    try:
        client = QdrantClient(path=str(QDRANT_PATH))
        try:
            if not client.collection_exists(QDRANT_COLLECTION):
                return "Qdrant Collection is missing."
            info = client.get_collection(QDRANT_COLLECTION)
        finally:
            client.close()
    except Exception:
        return "Qdrant Collection could not be checked."

    vectors = info.config.params.vectors
    if (
        not isinstance(vectors, models.VectorParams)
        or vectors.size != EMBEDDING_DIMENSION
        or vectors.distance != models.Distance.COSINE
        or not info.points_count
    ):
        return "Qdrant Collection does not match the configured embedding."
    return None


def _copy_eval_database(destination: Path) -> SQLiteDatabase:
    shutil.copy2(DEFAULT_DATABASE_PATH, destination)
    db = SQLiteDatabase(destination)
    source = db.get_data_source(1)
    if not source or source["db_type"] != "sqlite" or not source["is_default"]:
        raise RuntimeError("Default data source 1 is unavailable")
    db.update_data_source(1, database_url=str(destination))
    return db


def main() -> int:
    error = _precondition_error()
    if error:
        print(f"Real DeepSeek RAG A/B unavailable: {error}", file=sys.stderr)
        return 2

    try:
        llm = SQLOnlyLLMClient(
            DeepSeekLLMClient(
                api_key=DEEPSEEK_API_KEY,
                model=DEEPSEEK_MODEL,
                base_url=DEEPSEEK_BASE_URL,
                timeout_seconds=DEEPSEEK_TIMEOUT_SECONDS,
            )
        )
        knowledge = QdrantKnowledgeBase(
            path=QDRANT_PATH,
            collection_name=QDRANT_COLLECTION,
            embedder=BGEEmbedder(EMBEDDING_MODEL),
            top_k=KNOWLEDGE_TOP_K,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = _copy_eval_database(Path(tmp_dir) / "rag-ab.db")
            agents = {
                "off": DataAnalysisAgent(db=db, llm=llm),
                "on": DataAnalysisAgent(db=db, llm=llm, knowledge=knowledge),
            }
            scores = {"off": 0, "on": 0}
            print("Real DeepSeek RAG A/B")
            for case in CASES:
                print(case["id"])
                for arm, agent in agents.items():
                    result = agent.run(case["question"], data_source_id=1)
                    failures = _case_failures(
                        case, result, require_knowledge=arm == "on"
                    )
                    scores[arm] += not failures
                    detail = f" - {'; '.join(failures)}" if failures else ""
                    print(f"  {arm}: {'FAIL' if failures else 'PASS'}{detail}")
    except Exception as exc:
        print(f"Real DeepSeek RAG A/B failed: {type(exc).__name__}", file=sys.stderr)
        return 1

    total = len(CASES)
    delta = scores["on"] - scores["off"]
    delta_text = "tie" if delta == 0 else f"{delta:+d}"
    print(f"Totals: off {scores['off']}/{total}, on {scores['on']}/{total}")
    print(f"Delta: {delta_text}")
    return 0 if scores["on"] == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
