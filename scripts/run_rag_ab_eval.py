from __future__ import annotations

import math
import shutil
import sys
import tempfile
from numbers import Real
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
        "reference_sql": """
            SELECT product_name, ROUND(SUM(amount), 2) AS sales_amount
            FROM orders
            WHERE status = 'paid' AND created_at >= date('now', '-30 days')
            GROUP BY product_name
            ORDER BY sales_amount DESC
            LIMIT 5
        """,
        "label_field": "product_name",
        "metric_field": "sales_amount",
        "metric_aliases": {"sales_amount", "total_amount", "total_sales", "sales"},
        "metric_tolerance": 0.01,
        "required_tables": {"orders"},
        "required_columns": {"product_name", "amount", "status", "created_at"},
        "required_literals": {"paid", "-30 days"},
    },
    {
        "id": "gross_profit_by_brand",
        "question": "按品牌比较已成交订单的毛利，列出最高的5个品牌。",
        "reference_sql": """
            SELECT p.brand, ROUND(SUM(o.amount - p.cost_price), 2) AS gross_profit
            FROM orders AS o
            JOIN products AS p ON o.product_id = p.id
            WHERE o.status = 'paid'
            GROUP BY p.brand
            ORDER BY gross_profit DESC
            LIMIT 5
        """,
        "label_field": "brand",
        "metric_field": "gross_profit",
        "metric_aliases": {"gross_profit", "total_gross_profit", "profit"},
        "metric_tolerance": 0.01,
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
    },
    {
        "id": "category_refund_rate",
        "question": "想看各商品品类的退款占比排行，退款应按发生退款的订单来认定。",
        "reference_sql": """
            SELECT category,
                   COUNT(*) AS order_count,
                   SUM(CASE WHEN refund_amount > 0 OR status = 'refunded'
                            THEN 1 ELSE 0 END) AS refund_count,
                   ROUND(SUM(CASE WHEN refund_amount > 0 OR status = 'refunded'
                                  THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS refund_rate
            FROM orders
            GROUP BY category
            ORDER BY refund_rate DESC, refund_count DESC
            LIMIT 5
        """,
        "label_field": "category",
        "metric_field": "refund_rate",
        "metric_aliases": {"refund_rate", "rate"},
        "metric_tolerance": 0.0001,
        "required_tables": {"orders"},
        "required_columns": {"category", "refund_amount", "status"},
        "required_literals": {"refunded", "0"},
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
    case: dict[str, Any],
    result: dict[str, Any],
    require_knowledge: bool,
    expected_rows: list[dict[str, Any]] | None = None,
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

    if expected_rows is not None:
        failures.extend(_result_failures(case, result.get("data", []), expected_rows))

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


def _result_failures(
    case: dict[str, Any],
    actual_rows: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
) -> list[str]:
    failures = []
    if len(actual_rows) != len(expected_rows):
        failures.append("result row count differs from reference")

    label_field = case["label_field"]
    if [row.get(label_field) for row in actual_rows] != [
        row.get(label_field) for row in expected_rows
    ]:
        failures.append("ordered labels differ from reference")

    metric_field = _actual_metric_field(case, actual_rows)
    if metric_field is None:
        failures.append("primary metric is missing or ambiguous")
    elif len(actual_rows) == len(expected_rows) and any(
        not _numbers_close(
            actual.get(metric_field),
            expected.get(case["metric_field"]),
            case["metric_tolerance"],
        )
        for actual, expected in zip(actual_rows, expected_rows)
    ):
        failures.append("primary metric differs from reference")
    return failures


def _actual_metric_field(
    case: dict[str, Any], rows: list[dict[str, Any]]
) -> str | None:
    if not rows:
        return None
    keys = set.intersection(*(set(row) for row in rows))
    aliases = {
        key
        for key in keys
        if key.lower() in case["metric_aliases"]
        and all(_is_number(row[key]) for row in rows)
    }
    if len(aliases) == 1:
        return aliases.pop()
    if aliases:
        return None
    numeric = {
        key
        for key in keys
        if key != case["label_field"]
        and "count" not in key.lower()
        and all(_is_number(row[key]) for row in rows)
    }
    return numeric.pop() if len(numeric) == 1 else None


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _numbers_close(actual: Any, expected: Any, tolerance: float) -> bool:
    return _is_number(actual) and _is_number(expected) and math.isclose(
        float(actual), float(expected), rel_tol=1e-9, abs_tol=tolerance
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


def _reference_rows(db: SQLiteDatabase) -> dict[str, list[dict[str, Any]]]:
    return {case["id"]: db.execute_select(case["reference_sql"]) for case in CASES}


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
            expected_rows = _reference_rows(db)
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
                        case,
                        result,
                        require_knowledge=arm == "on",
                        expected_rows=expected_rows[case["id"]],
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
