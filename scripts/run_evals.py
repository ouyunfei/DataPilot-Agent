from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.workflow import DataAnalysisAgent
from app.db.database import SQLiteDatabase
from app.services.llm import SQLGeneration
from app.services.sql_validator import SQLSafetyError, validate_select_sql


RAG_CASES = [
    {
        "id": "paid_sales_only",
        "question": "请计算有效销售订单的总销售额。",
        "reference_context": "参考知识：有效销售额只统计 status = 'paid' 的订单。",
        "baseline_sql": "SELECT ROUND(SUM(amount), 2) AS sales_amount FROM orders",
        "rag_sql": (
            "SELECT ROUND(SUM(amount), 2) AS sales_amount FROM orders "
            "WHERE status = 'paid'"
        ),
        "expected_sql_fragments": ["SUM(amount)", "WHERE status = 'paid'"],
    },
    {
        "id": "gross_profit_by_brand",
        "question": "请按品牌计算毛利排行。",
        "reference_context": (
            "参考知识：毛利等于订单金额减商品成本价，关联条件是 "
            "orders.product_id = products.id，且只统计已支付订单。"
        ),
        "baseline_sql": (
            "SELECT products.brand, ROUND(SUM(orders.amount), 2) AS gross_profit "
            "FROM orders JOIN products ON orders.product_id = products.id "
            "GROUP BY products.brand ORDER BY gross_profit DESC"
        ),
        "rag_sql": (
            "SELECT products.brand, "
            "ROUND(SUM(orders.amount - products.cost_price), 2) AS gross_profit "
            "FROM orders JOIN products ON orders.product_id = products.id "
            "WHERE orders.status = 'paid' GROUP BY products.brand "
            "ORDER BY gross_profit DESC"
        ),
        "expected_sql_fragments": [
            "orders.amount - products.cost_price",
            "orders.product_id = products.id",
            "orders.status = 'paid'",
        ],
    },
    {
        "id": "order_created_at",
        "question": "请按实际下单日期汇总订单数量。",
        "reference_context": "参考知识：实际下单日期使用 orders.created_at，不是用户注册日期。",
        "baseline_sql": (
            "SELECT users.registered_at AS order_date, COUNT(orders.id) AS order_count "
            "FROM orders JOIN users ON orders.user_id = users.id "
            "GROUP BY users.registered_at ORDER BY order_date"
        ),
        "rag_sql": (
            "SELECT orders.created_at AS order_date, COUNT(orders.id) AS order_count "
            "FROM orders GROUP BY orders.created_at ORDER BY order_date"
        ),
        "expected_sql_fragments": [
            "orders.created_at AS order_date",
            "GROUP BY orders.created_at",
        ],
        "forbidden_sql_fragments": ["users.registered_at"],
    },
]


class EvalLLMClient:
    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        sql = _sql_for_question(question)
        return SQLGeneration(sql=sql, sql_explanation="Eval 使用固定 SQL 验证 Agent 工作流。")

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict[str, Any]],
    ) -> str:
        return f"Eval 查询返回 {len(rows)} 行结果。"


class RAGEvalLLMClient(EvalLLMClient):
    def __init__(self) -> None:
        self.cases = {item["question"]: item for item in RAG_CASES}

    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        item = self.cases[question]
        sql = item["rag_sql"] if item["reference_context"] in schema else item["baseline_sql"]
        return SQLGeneration(sql=sql, sql_explanation="Eval 根据是否注入参考知识选择固定 SQL。")


class RAGEvalKnowledgeRetriever:
    def retrieve(
        self, question: str, data_source_id: int
    ) -> tuple[str, list[dict[str, Any]]]:
        item = next(item for item in RAG_CASES if item["question"] == question)
        return item["reference_context"], [
            {
                "knowledge_type": "eval_reference",
                "source_id": item["id"],
                "title": item["id"],
                "score": 1.0,
            }
        ]


def main() -> int:
    questions = json.loads((ROOT / "evals" / "questions.json").read_text(encoding="utf-8"))
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        db = SQLiteDatabase(Path(tmp_dir) / "eval.db")
        db.initialize()
        agent = DataAnalysisAgent(db=db, llm=EvalLLMClient())

        for item in questions:
            result = agent.run(item["question"])
            failures.extend(_check_case(item, result))

        rag_off, rag_on, rag_execution_ok = _run_rag_comparison(db)

    passed = len(questions) - len({failure.split(':', 1)[0] for failure in failures})
    total = len(questions)
    print(f"Eval passed: {passed}/{total}")
    print(f"Success rate: {passed / total * 100:.2f}%")
    rag_total = len(RAG_CASES)
    print(f"RAG comparison: off {rag_off}/{rag_total}, on {rag_on}/{rag_total}")
    print(f"RAG improvement: +{(rag_on - rag_off) / rag_total * 100:.2f}pp")

    if failures:
        print("Failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    if not rag_execution_ok or rag_on != rag_total or rag_on <= rag_off:
        return 1
    return 0


def _check_case(item: dict[str, Any], result: dict[str, Any]) -> list[str]:
    case_id = item["id"]
    failures: list[str] = []
    sql = result.get("sql", "")
    rows = result.get("data", [])
    chart = result.get("chart", {})
    error = result.get("error")

    if item.get("should_be_safe", True):
        if not sql:
            failures.append(f"{case_id}: SQL was not generated")
        try:
            validate_select_sql(sql)
        except SQLSafetyError as exc:
            failures.append(f"{case_id}: SQL safety validation failed: {exc}")
        if error:
            failures.append(f"{case_id}: agent returned error: {error}")
    elif not error:
        failures.append(f"{case_id}: expected unsafe query to fail")

    if not rows:
        failures.append(f"{case_id}: query returned no data")
    else:
        missing_fields = set(item["expected_fields"]) - set(rows[0].keys())
        if missing_fields:
            failures.append(f"{case_id}: missing fields {sorted(missing_fields)}")

    if chart.get("type") != item["expected_chart_type"]:
        failures.append(
            f"{case_id}: expected chart {item['expected_chart_type']}, got {chart.get('type')}"
        )

    return failures


def _sql_for_question(question: str) -> str:
    if "每天" in question or "趋势" in question:
        return """
        SELECT
            created_at AS order_date,
            ROUND(SUM(amount), 2) AS total_amount
        FROM orders
        WHERE status = 'paid'
          AND created_at >= date('now', '-30 days')
        GROUP BY created_at
        ORDER BY order_date
        LIMIT 30
        """
    if "城市" in question:
        return """
        SELECT
            city,
            ROUND(SUM(amount), 2) AS total_amount,
            COUNT(*) AS order_count
        FROM orders
        WHERE status = 'paid'
        GROUP BY city
        ORDER BY total_amount DESC
        LIMIT 10
        """
    if "用户的消费金额" in question:
        return """
        SELECT
            users.name AS user_name,
            ROUND(SUM(orders.amount), 2) AS total_amount,
            COUNT(*) AS order_count
        FROM orders
        JOIN users ON orders.user_id = users.id
        WHERE orders.status = 'paid'
        GROUP BY users.id, users.name
        ORDER BY total_amount DESC
        LIMIT 5
        """
    if "用户等级" in question or "客单价" in question:
        return """
        SELECT
            users.level,
            ROUND(SUM(orders.amount) * 1.0 / COUNT(orders.id), 2) AS average_order_value,
            COUNT(*) AS order_count
        FROM orders
        JOIN users ON orders.user_id = users.id
        WHERE orders.status = 'paid'
        GROUP BY users.level
        ORDER BY average_order_value DESC
        LIMIT 5
        """
    if "品牌" in question:
        return """
        SELECT
            products.brand,
            ROUND(SUM(orders.amount), 2) AS total_amount,
            COUNT(*) AS order_count
        FROM orders
        JOIN products ON orders.product_id = products.id
        WHERE orders.status = 'paid'
        GROUP BY products.brand
        ORDER BY total_amount DESC
        LIMIT 5
        """
    return """
    SELECT
        product_name,
        ROUND(SUM(amount), 2) AS total_amount,
        COUNT(*) AS order_count
    FROM orders
    WHERE status = 'paid'
    GROUP BY product_name
    ORDER BY total_amount DESC
    LIMIT 5
    """


def _run_rag_comparison(db: SQLiteDatabase) -> tuple[int, int, bool]:
    llm = RAGEvalLLMClient()
    agents = (
        DataAnalysisAgent(db=db, llm=llm),
        DataAnalysisAgent(db=db, llm=llm, knowledge=RAGEvalKnowledgeRetriever()),
    )
    scores: list[int] = []
    all_executable = True
    for agent in agents:
        results = [agent.run(item["question"]) for item in RAG_CASES]
        all_executable &= all(not result.get("error") and result.get("data") for result in results)
        scores.append(sum(_rag_case_passes(item, result) for item, result in zip(RAG_CASES, results)))
    return scores[0], scores[1], all_executable


def _rag_case_passes(item: dict[str, Any], result: dict[str, Any]) -> bool:
    sql = " ".join(result.get("sql", "").lower().split())
    return (
        not result.get("error")
        and bool(result.get("data"))
        and all(fragment.lower() in sql for fragment in item["expected_sql_fragments"])
        and not any(
            fragment.lower() in sql for fragment in item.get("forbidden_sql_fragments", [])
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
