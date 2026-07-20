from pathlib import Path
from types import SimpleNamespace

import pytest
from qdrant_client import models

from app.db.database import SQLiteDatabase
from app.services.knowledge import EMBEDDING_MODEL_NAME
from app.services.llm import SQLGeneration
from scripts import run_rag_ab_eval as rag_ab


@pytest.mark.parametrize(
    ("case_id", "actual_metric"),
    [
        ("paid_sales_30_day_ranking", "total_sales"),
        ("gross_profit_by_brand", "profit"),
        ("category_refund_rate", "rate"),
    ],
)
def test_case_failures_accepts_equivalent_results_with_metric_alias(
    case_id, actual_metric
):
    case = next(item for item in rag_ab.CASES if item["id"] == case_id)
    label = case["label_field"]
    metric = case["metric_field"]
    expected_rows = [
        {label: "A", metric: 10.0},
        {label: "B", metric: 8.0},
    ]
    actual_rows = [
        {
            label: "A",
            actual_metric: 10.0 + case["metric_tolerance"] / 2,
            "order_count": 3,
        },
        {label: "B", actual_metric: 8.0, "order_count": 2},
    ]

    assert rag_ab._case_failures(
        case,
        {"sql": case["reference_sql"], "data": actual_rows, "error": None},
        require_knowledge=False,
        expected_rows=expected_rows,
    ) == []


@pytest.mark.parametrize(
    ("case_id", "wrong_sql", "actual_rows", "expected_failure"),
    [
        (
            "paid_sales_30_day_ranking",
            """
            SELECT product_name, SUM(amount) AS total_amount, status, created_at
            FROM orders
            WHERE status != 'paid' OR created_at < date('now', '-30 days')
            GROUP BY product_name
            ORDER BY total_amount ASC
            LIMIT 3
            """,
            [
                {"product_name": "B", "total_amount": 8.0},
                {"product_name": "A", "total_amount": 10.0},
            ],
            "ordered labels differ from reference",
        ),
        (
            "gross_profit_by_brand",
            """
            SELECT p.brand, SUM(p.cost_price - o.amount) AS gross_profit,
                   o.product_id, p.id, o.status
            FROM orders AS o
            JOIN products AS p ON o.product_id = p.id OR 1 = 1
            WHERE o.status = 'paid'
            GROUP BY p.brand
            ORDER BY gross_profit DESC
            LIMIT 5
            """,
            [
                {"brand": "A", "gross_profit": -10.0},
                {"brand": "B", "gross_profit": -8.0},
            ],
            "primary metric differs from reference",
        ),
        (
            "category_refund_rate",
            """
            SELECT category,
                   COUNT(*) * 1.0 / SUM(CASE WHEN refund_amount > 0
                                             OR status = 'refunded' THEN 1 ELSE 0 END)
                       AS refund_rate
            FROM orders
            GROUP BY category
            ORDER BY refund_rate DESC
            LIMIT 5
            """,
            [
                {"category": "A", "refund_rate": 0.9},
                {"category": "B", "refund_rate": 0.8},
            ],
            "primary metric differs from reference",
        ),
    ],
)
def test_case_failures_rejects_term_complete_sql_with_wrong_results(
    case_id, wrong_sql, actual_rows, expected_failure
):
    case = next(item for item in rag_ab.CASES if item["id"] == case_id)
    label = case["label_field"]
    metric = case["metric_field"]
    expected_rows = [
        {label: "A", metric: 10.0 if case_id != "category_refund_rate" else 0.1},
        {label: "B", metric: 8.0 if case_id != "category_refund_rate" else 0.2},
    ]

    failures = rag_ab._case_failures(
        case,
        {"sql": wrong_sql, "data": actual_rows, "error": None},
        require_knowledge=False,
        expected_rows=expected_rows,
    )

    assert expected_failure in failures


def test_case_failures_rejects_wrong_row_count_and_ambiguous_metric():
    case = next(
        item for item in rag_ab.CASES if item["id"] == "paid_sales_30_day_ranking"
    )
    expected_rows = [
        {"product_name": "A", "sales_amount": 10.0},
        {"product_name": "B", "sales_amount": 8.0},
    ]
    actual_rows = [{"product_name": "A", "revenue": 10.0, "average": 5.0}]

    failures = rag_ab._case_failures(
        case,
        {"sql": case["reference_sql"], "data": actual_rows, "error": None},
        require_knowledge=False,
        expected_rows=expected_rows,
    )

    assert "result row count differs from reference" in failures
    assert "primary metric is missing or ambiguous" in failures


def test_reference_rows_executes_each_reference_query_once():
    calls = []

    class FakeDatabase:
        def execute_select(self, sql):
            calls.append(sql)
            return [{"value": len(calls)}]

    rows = rag_ab._reference_rows(FakeDatabase())

    assert calls == [case["reference_sql"] for case in rag_ab.CASES]
    assert list(rows) == [case["id"] for case in rag_ab.CASES]


def test_case_failures_accepts_required_tables_columns_and_literals():
    case = {
        "required_tables": {"orders", "products"},
        "required_columns": {"brand", "amount", "cost_price", "product_id", "id", "status"},
        "required_literals": {"paid"},
    }
    result = {
        "sql": """
            SELECT p.brand, ROUND(SUM(o.amount - p.cost_price), 2) AS gross_profit
            FROM orders AS o
            JOIN products AS p ON o.product_id = p.id
            WHERE o.status = 'paid'
            GROUP BY p.brand
            ORDER BY gross_profit DESC
            LIMIT 5
        """,
        "data": [{"brand": "HomePro", "gross_profit": 123.45}],
        "error": None,
        "knowledge_sources": [],
    }

    assert rag_ab._case_failures(case, result, require_knowledge=False) == []


def test_case_failures_reports_execution_semantic_and_retrieval_failures():
    case = {
        "required_tables": {"orders"},
        "required_columns": {"category", "refund_amount", "status"},
        "required_literals": {"refunded", "0"},
    }
    result = {
        "sql": "SELECT category, COUNT(*) FROM orders GROUP BY category LIMIT 5",
        "data": [],
        "error": "private failure detail",
        "knowledge_sources": [],
    }

    assert rag_ab._case_failures(case, result, require_knowledge=True) == [
        "agent error",
        "query returned no data",
        "missing columns: refund_amount, status",
        "missing literals: 0, refunded",
        "knowledge was not retrieved",
    ]


@pytest.mark.parametrize("api_key", ["", "  ", "your_deepseek_api_key", "placeholder"])
def test_main_refuses_placeholder_key_without_loading_qdrant(
    monkeypatch, capsys, tmp_path, api_key
):
    monkeypatch.setattr(rag_ab, "DEEPSEEK_API_KEY", api_key)
    monkeypatch.setattr(rag_ab, "QDRANT_PATH", tmp_path / "private-index")
    monkeypatch.setattr(
        rag_ab,
        "QdrantClient",
        lambda **_kwargs: pytest.fail("Qdrant must not load without an API key"),
    )

    assert rag_ab.main() == 2

    stdout, stderr = capsys.readouterr()
    assert stdout == ""
    assert stderr == (
        "Real DeepSeek RAG A/B unavailable: DeepSeek API key is not configured.\n"
    )
    assert str(tmp_path) not in stderr
    if api_key.strip():
        assert api_key not in stderr


def test_precondition_error_hides_missing_qdrant_path(monkeypatch, tmp_path):
    _configure_valid_files(monkeypatch, tmp_path)
    missing_path = tmp_path / "private-missing-index"
    monkeypatch.setattr(rag_ab, "QDRANT_PATH", missing_path)

    assert rag_ab._precondition_error() == "Qdrant path is unavailable."


@pytest.mark.parametrize(
    ("exists", "vectors", "expected"),
    [
        (False, None, "Qdrant Collection is missing."),
        (
            True,
            models.VectorParams(size=3, distance=models.Distance.COSINE),
            "Qdrant Collection does not match the configured embedding.",
        ),
    ],
)
def test_precondition_error_rejects_missing_or_mismatched_collection(
    monkeypatch, tmp_path, exists, vectors, expected
):
    _configure_valid_files(monkeypatch, tmp_path)

    class FakeClient:
        def collection_exists(self, _name):
            return exists

        def get_collection(self, _name):
            return SimpleNamespace(
                config=SimpleNamespace(params=SimpleNamespace(vectors=vectors)),
                points_count=286,
            )

        def close(self):
            pass

    monkeypatch.setattr(rag_ab, "QdrantClient", lambda **_kwargs: FakeClient())

    assert rag_ab._precondition_error() == expected


def test_copy_eval_database_repoints_source_one_without_changing_source(
    monkeypatch, tmp_path
):
    source_path = tmp_path / "source.db"
    source = SQLiteDatabase(source_path)
    source.initialize()
    monkeypatch.setattr(rag_ab, "DEFAULT_DATABASE_PATH", source_path)
    copied_path = tmp_path / "copied.db"

    copied = rag_ab._copy_eval_database(copied_path)

    assert copied.path == copied_path
    assert copied.get_data_source(1)["database_url"] == str(copied_path)
    assert source.get_data_source(1)["database_url"] == str(source_path)


def test_sql_only_client_delegates_generation_and_skips_analysis_api():
    calls = []

    class Delegate:
        def generate_sql(self, question, schema):
            calls.append((question, schema))
            return SQLGeneration(sql="SELECT id FROM orders LIMIT 1", sql_explanation="ok")

    client = rag_ab.SQLOnlyLLMClient(Delegate())

    generation = client.generate_sql("question", "schema")

    assert generation.sql == "SELECT id FROM orders LIMIT 1"
    assert calls == [("question", "schema")]
    assert client.analyze_result("q", "sql", "explanation", []) == rag_ab.FIXED_ANALYSIS


def _configure_valid_files(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "datapilot.db"
    SQLiteDatabase(database_path).initialize()
    qdrant_path = tmp_path / "qdrant"
    qdrant_path.mkdir()
    monkeypatch.setattr(rag_ab, "DEEPSEEK_API_KEY", "real-test-key")
    monkeypatch.setattr(rag_ab, "DEFAULT_DATABASE_PATH", database_path)
    monkeypatch.setattr(rag_ab, "QDRANT_PATH", qdrant_path)
    monkeypatch.setattr(rag_ab, "EMBEDDING_MODEL", EMBEDDING_MODEL_NAME)
