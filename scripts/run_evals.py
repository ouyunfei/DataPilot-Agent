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

    passed = len(questions) - len({failure.split(':', 1)[0] for failure in failures})
    total = len(questions)
    print(f"Eval passed: {passed}/{total}")
    print(f"Success rate: {passed / total * 100:.2f}%")

    if failures:
        print("Failures:")
        for failure in failures:
            print(f"- {failure}")
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


if __name__ == "__main__":
    raise SystemExit(main())
