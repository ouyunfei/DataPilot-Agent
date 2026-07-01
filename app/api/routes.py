from fastapi import APIRouter, HTTPException, Query

from app.agent.workflow import DataAnalysisAgent
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    FeedbackResponse,
    QueryLogFeedbackRequest,
    QueryLogListResponse,
    QueryStatsResponse,
    SecurityPolicyResponse,
)
from app.services.sql_validator import ALLOWED_TABLES, FORBIDDEN_KEYWORDS, MAX_LIMIT


def create_chat_router(agent: DataAnalysisAgent) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["chat"])

    @router.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        result = agent.run(request.question, session_id=request.session_id)
        return ChatResponse(
            question=request.question,
            session_id=result.get("session_id", ""),
            sql=result.get("sql", ""),
            sql_explanation=result.get("sql_explanation", ""),
            data=result.get("data", []),
            chart=result.get("chart", {}),
            trusted_answer=result.get("trusted_answer", False),
            answer=result.get("answer", ""),
            error=result.get("error"),
        )

    @router.get("/query-logs", response_model=QueryLogListResponse)
    def query_logs(limit: int = Query(default=20, ge=1, le=100)) -> QueryLogListResponse:
        return QueryLogListResponse(items=agent.db.list_query_logs(limit=limit))

    @router.get("/query-stats", response_model=QueryStatsResponse)
    def query_stats() -> QueryStatsResponse:
        return QueryStatsResponse(**agent.db.get_query_stats())

    @router.post("/query-logs/{log_id}/feedback", response_model=FeedbackResponse)
    def save_query_feedback(
        log_id: int,
        request: QueryLogFeedbackRequest,
    ) -> FeedbackResponse:
        updated = agent.db.update_query_feedback(
            log_id=log_id,
            feedback=request.feedback,
            note=request.note,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="query log not found")
        return FeedbackResponse(ok=True)

    @router.get("/security/policies", response_model=SecurityPolicyResponse)
    def security_policies() -> SecurityPolicyResponse:
        return SecurityPolicyResponse(
            allow_only_select=True,
            forbid_multiple_statements=True,
            forbid_comments=True,
            forbid_select_star=True,
            allowed_tables=sorted(ALLOWED_TABLES),
            forbidden_keywords=sorted(FORBIDDEN_KEYWORDS),
            max_limit=MAX_LIMIT,
        )

    return router
