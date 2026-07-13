from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.core.config import QUERY_TIMEOUT_SECONDS
from app.db.database import SQLiteDatabase
from app.services.insights import recommend_insights
from app.services.llm import BaseLLMClient
from app.services.semantic import build_semantic_context, find_trusted_answer, recommend_chart
from app.services.sql_validator import SQLSafetyError, validate_select_sql


class AnalysisState(TypedDict, total=False):
    question: str
    session_id: str
    session_context: str
    data_source_id: int
    data_source: dict[str, Any]
    schema: str
    sql: str
    sql_explanation: str
    validated_sql: str
    data: list[dict[str, Any]]
    chart: dict[str, str]
    insights: list[dict[str, str]]
    trusted_answer: bool
    answer: str
    error: str | None
    error_code: str | None


class DataAnalysisAgent:
    """LangGraph-powered data analysis workflow."""

    def __init__(self, db: SQLiteDatabase, llm: BaseLLMClient) -> None:
        self.db = db
        self.llm = llm
        self.graph = self._build_graph()

    def run(
        self,
        question: str,
        session_id: str | None = None,
        data_source_id: int | None = None,
    ) -> AnalysisState:
        session_id = self.db.create_session(session_id)
        session_context = self.db.get_recent_session_context(session_id)
        data_source = (
            self.db.get_data_source(data_source_id)
            if data_source_id is not None
            else self.db.get_default_data_source()
        )
        if data_source is None:
            result: AnalysisState = {
                "question": question,
                "session_id": session_id,
                "data_source_id": data_source_id or 0,
                "sql": "",
                "sql_explanation": "",
                "data": [],
                "chart": {},
                "insights": [],
                "trusted_answer": False,
                "answer": "",
                "error": "数据源不存在",
                "error_code": "data_source_error",
            }
            self.db.log_query(question, "", False, "", 0, result["error"], 0, result["error_code"])
            self.db.save_chat_message(session_id, question, "", "")
            return result

        started_at = time.perf_counter()
        result = self.graph.invoke(
            {
                "question": question,
                "session_id": session_id,
                "session_context": session_context,
                "data_source_id": data_source["id"],
                "data_source": data_source,
                "schema": "",
                "sql": "",
                "sql_explanation": "",
                "validated_sql": "",
                "data": [],
                "chart": {},
                "insights": [],
                "trusted_answer": False,
                "answer": "",
                "error": None,
                "error_code": None,
            }
        )
        result["data_source_id"] = data_source["id"]
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        self.db.log_query(
            question=question,
            sql=result.get("sql", ""),
            trusted_answer=bool(result.get("trusted_answer")),
            chart_type=result.get("chart", {}).get("type", ""),
            row_count=len(result.get("data", [])),
            error=result.get("error"),
            duration_ms=duration_ms,
            error_code=result.get("error_code"),
        )
        self.db.save_chat_message(
            session_id=session_id,
            question=question,
            sql=result.get("sql", ""),
            answer=result.get("answer", ""),
        )
        result["session_id"] = session_id
        return result

    def _build_graph(self):
        workflow = StateGraph(AnalysisState)

        workflow.add_node("retrieve_schema", self._retrieve_schema)
        workflow.add_node("generate_sql", self._generate_sql)
        workflow.add_node("validate_sql", self._validate_sql)
        workflow.add_node("execute_sql", self._execute_sql)
        workflow.add_node("analyze_result", self._analyze_result)

        workflow.add_edge(START, "retrieve_schema")
        workflow.add_edge("retrieve_schema", "generate_sql")
        workflow.add_edge("generate_sql", "validate_sql")
        workflow.add_conditional_edges(
            "validate_sql",
            self._route_after_validation,
            {
                "execute_sql": "execute_sql",
                "analyze_result": "analyze_result",
            },
        )
        workflow.add_edge("execute_sql", "analyze_result")
        workflow.add_edge("analyze_result", END)

        return workflow.compile()

    def _retrieve_schema(self, state: AnalysisState) -> dict[str, str]:
        schema = (
            f"{self.db.get_data_source_schema_description(state['data_source'])}"
            f"\n\n{build_semantic_context(self.db.list_metrics(enabled_only=True), state['data_source']['allowed_tables'], state['data_source']['allowed_columns'])}"
        )
        if state.get("session_context"):
            schema = f"{schema}\n\n{state['session_context']}"
        return {"schema": schema}

    def _generate_sql(self, state: AnalysisState) -> dict[str, str | bool]:
        trusted_answer = (
            find_trusted_answer(state["question"])
            if state["data_source"]["db_type"] == "sqlite"
            else None
        )
        if trusted_answer:
            return {
                "sql": trusted_answer["sql"],
                "sql_explanation": trusted_answer["sql_explanation"],
                "trusted_answer": True,
            }

        try:
            generation = self.llm.generate_sql(
                question=state["question"],
                schema=state["schema"],
            )
        except Exception as exc:
            return {
                "error": f"LLM 调用失败：{exc}",
                "error_code": "llm_error",
                "sql": "",
                "sql_explanation": "",
            }

        return {
            "sql": generation.sql.strip(),
            "sql_explanation": generation.sql_explanation.strip(),
            "trusted_answer": False,
        }

    def _validate_sql(self, state: AnalysisState) -> dict[str, str | None]:
        if state.get("error"):
            return {"validated_sql": ""}

        try:
            validated_sql = validate_select_sql(
                state["sql"],
                allowed_tables=set(state["data_source"]["allowed_tables"]),
                allowed_columns={
                    table: set(columns)
                    for table, columns in state["data_source"]["allowed_columns"].items()
                },
                dialect={
                    "sqlite": "sqlite",
                    "postgresql": "postgres",
                    "mysql": "mysql",
                }[state["data_source"]["db_type"]],
            )
        except SQLSafetyError as exc:
            return {"error": str(exc), "error_code": "sql_safety_error", "validated_sql": ""}

        return {
            "sql": validated_sql,
            "validated_sql": validated_sql,
            "error": None,
            "error_code": None,
        }

    def _execute_sql(self, state: AnalysisState) -> dict[str, list[dict[str, Any]] | str | None]:
        if state["data_source"]["db_type"] not in {"sqlite", "postgresql", "mysql"}:
            return {
                "data": [],
                "error": "当前阶段仅支持 SQLite、PostgreSQL 和 MySQL 数据源执行查询",
                "error_code": "data_source_error",
            }

        try:
            rows = self.db.execute_data_source_select(
                state["data_source"],
                state["validated_sql"],
                timeout_seconds=QUERY_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            return {"data": [], "error": str(exc), "error_code": "query_timeout"}
        except Exception as exc:
            return {"data": [], "error": f"SQL 执行失败：{exc}", "error_code": "execution_error"}

        return {
            "data": rows,
            "chart": recommend_chart(rows),
            "insights": recommend_insights(rows),
            "error": None,
            "error_code": None,
        }

    def _analyze_result(self, state: AnalysisState) -> dict[str, str]:
        if state.get("error"):
            return {"answer": ""}

        try:
            answer = self.llm.analyze_result(
                question=state["question"],
                sql=state["validated_sql"],
                sql_explanation=state.get("sql_explanation", ""),
                rows=state.get("data", []),
            )
        except Exception as exc:
            return {"answer": "", "error": f"LLM 调用失败：{exc}", "error_code": "llm_error"}

        insight_messages = [item["message"] for item in state.get("insights", [])]
        if insight_messages:
            answer = f"{answer} {' '.join(insight_messages[:3])}"

        return {"answer": answer}

    @staticmethod
    def _route_after_validation(state: AnalysisState) -> str:
        if state.get("error"):
            return "analyze_result"
        return "execute_sql"
