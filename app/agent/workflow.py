from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.db.database import SQLiteDatabase
from app.services.llm import BaseLLMClient
from app.services.sql_validator import SQLSafetyError, validate_select_sql


class AnalysisState(TypedDict, total=False):
    question: str
    schema: str
    sql: str
    sql_explanation: str
    validated_sql: str
    data: list[dict[str, Any]]
    answer: str
    error: str | None


class DataAnalysisAgent:
    """LangGraph-powered data analysis workflow."""

    def __init__(self, db: SQLiteDatabase, llm: BaseLLMClient) -> None:
        self.db = db
        self.llm = llm
        self.graph = self._build_graph()

    def run(self, question: str) -> AnalysisState:
        return self.graph.invoke(
            {
                "question": question,
                "schema": "",
                "sql": "",
                "sql_explanation": "",
                "validated_sql": "",
                "data": [],
                "answer": "",
                "error": None,
            }
        )

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
        return {"schema": self.db.get_schema_description()}

    def _generate_sql(self, state: AnalysisState) -> dict[str, str]:
        try:
            generation = self.llm.generate_sql(
                question=state["question"],
                schema=state["schema"],
            )
        except Exception as exc:
            return {"error": f"LLM 调用失败：{exc}", "sql": "", "sql_explanation": ""}

        return {
            "sql": generation.sql.strip(),
            "sql_explanation": generation.sql_explanation.strip(),
        }

    def _validate_sql(self, state: AnalysisState) -> dict[str, str | None]:
        if state.get("error"):
            return {"validated_sql": ""}

        try:
            validated_sql = validate_select_sql(state["sql"])
        except SQLSafetyError as exc:
            return {"error": str(exc), "validated_sql": ""}

        return {"sql": validated_sql, "validated_sql": validated_sql, "error": None}

    def _execute_sql(self, state: AnalysisState) -> dict[str, list[dict[str, Any]] | str | None]:
        try:
            rows = self.db.execute_select(state["validated_sql"])
        except Exception as exc:
            return {"data": [], "error": f"SQL 执行失败：{exc}"}

        return {"data": rows, "error": None}

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
            return {"answer": "", "error": f"LLM 调用失败：{exc}"}

        return {"answer": answer}

    @staticmethod
    def _route_after_validation(state: AnalysisState) -> str:
        if state.get("error"):
            return "analyze_result"
        return "execute_sql"
