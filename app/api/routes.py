from fastapi import APIRouter, HTTPException, Query

from app.agent.workflow import DataAnalysisAgent
from app.core.config import QUERY_TIMEOUT_SECONDS
from app.schemas.chat import (
    CatalogColumnListResponse,
    CatalogTableListResponse,
    ChatRequest,
    ChatResponse,
    DataSourceCreateRequest,
    DataSourceItem,
    DataSourceListResponse,
    DataSourceTestResponse,
    DataSourceUpdateRequest,
    FeedbackResponse,
    MetricCreateRequest,
    MetricItem,
    MetricListResponse,
    MetricUpdateRequest,
    QueryLogFeedbackRequest,
    QueryLogListResponse,
    QueryStatsResponse,
    SecurityPolicyResponse,
)
from app.services.sql_validator import FORBIDDEN_KEYWORDS, MAX_LIMIT


def create_chat_router(agent: DataAnalysisAgent) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["chat"])

    @router.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        result = agent.run(
            request.question,
            session_id=request.session_id,
            data_source_id=request.data_source_id,
        )
        return ChatResponse(
            question=request.question,
            session_id=result.get("session_id", ""),
            data_source_id=result.get("data_source_id"),
            sql=result.get("sql", ""),
            sql_explanation=result.get("sql_explanation", ""),
            data=result.get("data", []),
            chart=result.get("chart", {}),
            insights=result.get("insights", []),
            trusted_answer=result.get("trusted_answer", False),
            answer=result.get("answer", ""),
            error=result.get("error"),
            error_code=result.get("error_code"),
        )

    @router.get("/data-sources", response_model=DataSourceListResponse)
    def data_sources() -> DataSourceListResponse:
        return DataSourceListResponse(items=agent.db.list_data_sources())

    @router.post("/data-sources", response_model=DataSourceItem)
    def create_data_source(request: DataSourceCreateRequest) -> DataSourceItem:
        try:
            source = agent.db.create_data_source(
                name=request.name,
                db_type=request.db_type,
                database_url=request.database_url,
                allowed_tables=request.allowed_tables,
                allowed_columns=request.allowed_columns,
                is_default=request.is_default,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return DataSourceItem(**source)

    @router.put("/data-sources/{source_id}", response_model=DataSourceItem)
    def update_data_source(
        source_id: int,
        request: DataSourceUpdateRequest,
    ) -> DataSourceItem:
        try:
            source = agent.db.update_data_source(
                source_id=source_id,
                database_url=request.database_url,
                allowed_tables=request.allowed_tables,
                allowed_columns=request.allowed_columns,
                is_default=request.is_default,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if source is None:
            raise HTTPException(status_code=404, detail="data source not found")
        return DataSourceItem(**source)

    @router.delete("/data-sources/{source_id}", response_model=FeedbackResponse)
    def delete_data_source(source_id: int) -> FeedbackResponse:
        try:
            deleted = agent.db.delete_data_source(source_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="data source not found")
        return FeedbackResponse(ok=True)

    @router.post("/data-sources/{source_id}/test", response_model=DataSourceTestResponse)
    def test_data_source(source_id: int) -> DataSourceTestResponse:
        if agent.db.get_data_source(source_id) is None:
            raise HTTPException(status_code=404, detail="data source not found")
        return DataSourceTestResponse(**agent.db.test_data_source(source_id))

    @router.get("/query-logs", response_model=QueryLogListResponse)
    def query_logs(limit: int = Query(default=20, ge=1, le=100)) -> QueryLogListResponse:
        return QueryLogListResponse(items=agent.db.list_query_logs(limit=limit))

    @router.get("/query-stats", response_model=QueryStatsResponse)
    def query_stats() -> QueryStatsResponse:
        return QueryStatsResponse(**agent.db.get_query_stats())

    @router.get("/catalog/tables", response_model=CatalogTableListResponse)
    def catalog_tables(data_source_id: int | None = None) -> CatalogTableListResponse:
        if data_source_id is not None and agent.db.get_data_source(data_source_id) is None:
            raise HTTPException(status_code=404, detail="data source not found")
        return CatalogTableListResponse(items=agent.db.list_catalog_tables(data_source_id))

    @router.get("/catalog/tables/{table_name}/columns", response_model=CatalogColumnListResponse)
    def catalog_columns(
        table_name: str,
        data_source_id: int | None = None,
    ) -> CatalogColumnListResponse:
        if data_source_id is not None and agent.db.get_data_source(data_source_id) is None:
            raise HTTPException(status_code=404, detail="data source not found")
        columns = agent.db.list_catalog_columns(table_name, data_source_id)
        if not columns:
            raise HTTPException(status_code=404, detail="table not found")
        return CatalogColumnListResponse(table=table_name, columns=columns)

    @router.get("/metrics", response_model=MetricListResponse)
    def metrics(enabled_only: bool = False) -> MetricListResponse:
        return MetricListResponse(items=agent.db.list_metrics(enabled_only=enabled_only))

    @router.post("/metrics", response_model=MetricItem)
    def create_metric(request: MetricCreateRequest) -> MetricItem:
        try:
            metric = agent.db.create_metric(
                metric_key=request.metric_key,
                name=request.name,
                expression=request.expression,
                description=request.description,
                enabled=request.enabled,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return MetricItem(**metric)

    @router.put("/metrics/{metric_id}", response_model=MetricItem)
    def update_metric(metric_id: int, request: MetricUpdateRequest) -> MetricItem:
        try:
            metric = agent.db.update_metric(
                metric_id=metric_id,
                metric_key=request.metric_key,
                name=request.name,
                expression=request.expression,
                description=request.description,
                enabled=request.enabled,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if metric is None:
            raise HTTPException(status_code=404, detail="metric not found")
        return MetricItem(**metric)

    @router.delete("/metrics/{metric_id}", response_model=FeedbackResponse)
    def delete_metric(metric_id: int) -> FeedbackResponse:
        if not agent.db.delete_metric(metric_id):
            raise HTTPException(status_code=404, detail="metric not found")
        return FeedbackResponse(ok=True)

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
    def security_policies(data_source_id: int | None = None) -> SecurityPolicyResponse:
        source = (
            agent.db.get_data_source(data_source_id)
            if data_source_id is not None
            else agent.db.get_default_data_source()
        )
        if source is None:
            raise HTTPException(status_code=404, detail="data source not found")

        return SecurityPolicyResponse(
            allow_only_select=True,
            forbid_multiple_statements=True,
            forbid_comments=True,
            forbid_select_star=True,
            allowed_tables=sorted(source["allowed_tables"]),
            allowed_columns=source["allowed_columns"],
            forbidden_keywords=sorted(FORBIDDEN_KEYWORDS),
            max_limit=MAX_LIMIT,
            query_timeout_seconds=QUERY_TIMEOUT_SECONDS,
        )

    return router
