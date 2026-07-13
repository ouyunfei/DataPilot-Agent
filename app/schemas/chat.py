from typing import Any
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_serializer


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户的自然语言数据分析问题")
    session_id: str | None = Field(default=None, description="多轮追问会话 ID")
    data_source_id: int | None = Field(default=None, description="数据源 ID，不传则使用默认数据源")


class KnowledgeSourceItem(BaseModel):
    knowledge_type: Literal["schema", "metric", "trusted_sql", "historical_qa"]
    source_id: str
    title: str
    score: float


class ChatResponse(BaseModel):
    question: str
    session_id: str = ""
    data_source_id: int | None = None
    sql: str = ""
    sql_explanation: str = ""
    data: list[dict[str, Any]] = Field(default_factory=list)
    chart: dict[str, Any] = Field(default_factory=dict)
    insights: list[dict[str, str]] = Field(default_factory=list)
    knowledge_sources: list[KnowledgeSourceItem] = Field(default_factory=list)
    trusted_answer: bool = False
    answer: str = ""
    error: str | None = None
    error_code: str | None = None


class QueryLogItem(BaseModel):
    id: int
    question: str
    sql: str
    trusted_answer: bool
    chart_type: str
    row_count: int
    error: str | None = None
    error_code: str | None = None
    feedback: str | None = None
    feedback_note: str | None = None
    duration_ms: int
    created_at: str


class QueryLogListResponse(BaseModel):
    items: list[QueryLogItem] = Field(default_factory=list)


class QueryLogFeedbackRequest(BaseModel):
    feedback: Literal["like", "dislike"]
    note: str | None = Field(default=None, max_length=500)


class FeedbackResponse(BaseModel):
    ok: bool


class TopQuestionItem(BaseModel):
    question: str
    count: int


class QueryStatsResponse(BaseModel):
    total_queries: int
    success_queries: int
    failed_queries: int
    trusted_answer_queries: int
    average_duration_ms: float
    chart_type_counts: dict[str, int] = Field(default_factory=dict)
    feedback_counts: dict[str, int] = Field(default_factory=dict)
    error_code_counts: dict[str, int] = Field(default_factory=dict)
    top_questions: list[TopQuestionItem] = Field(default_factory=list)


class MetricItem(BaseModel):
    id: int
    metric_key: str
    name: str
    expression: str
    description: str
    enabled: bool
    created_at: str
    updated_at: str


class MetricListResponse(BaseModel):
    items: list[MetricItem] = Field(default_factory=list)


class MetricCreateRequest(BaseModel):
    metric_key: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(..., min_length=1, max_length=100)
    expression: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1, max_length=500)
    enabled: bool = True


class MetricUpdateRequest(BaseModel):
    metric_key: str | None = Field(default=None, min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    expression: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    enabled: bool | None = None


class DataSourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    db_type: Literal["sqlite", "mysql", "postgresql"]
    database_url: str = Field(..., min_length=1, max_length=1000)
    allowed_tables: list[str] = Field(..., min_length=1)
    allowed_columns: dict[str, list[str]] | None = None
    is_default: bool = False


class DataSourceUpdateRequest(BaseModel):
    database_url: str | None = Field(default=None, min_length=1, max_length=1000)
    allowed_tables: list[str] | None = Field(default=None, min_length=1)
    allowed_columns: dict[str, list[str]] | None = None
    is_default: bool | None = None


class DataSourceItem(BaseModel):
    id: int
    name: str
    db_type: str
    database_url: str
    allowed_tables: list[str]
    allowed_columns: dict[str, list[str]]
    is_default: bool
    created_at: str

    @field_serializer("database_url")
    def mask_database_password(self, database_url: str) -> str:
        parsed = urlsplit(database_url)
        if parsed.password is None:
            return database_url

        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        user = parsed.username or ""
        port = f":{parsed.port}" if parsed.port else ""
        return urlunsplit(
            (parsed.scheme, f"{user}:***@{host}{port}", parsed.path, parsed.query, parsed.fragment)
        )


class DataSourceListResponse(BaseModel):
    items: list[DataSourceItem] = Field(default_factory=list)


class DataSourceTestResponse(BaseModel):
    ok: bool
    message: str


class HealthResponse(BaseModel):
    status: str
    database_status: str
    deepseek_configured: bool
    table_count: int


class SecurityPolicyResponse(BaseModel):
    allow_only_select: bool
    forbid_multiple_statements: bool
    forbid_comments: bool
    forbid_select_star: bool
    allowed_tables: list[str]
    allowed_columns: dict[str, list[str]]
    forbidden_keywords: list[str]
    max_limit: int
    query_timeout_seconds: float


class CatalogTableItem(BaseModel):
    name: str
    description: str
    queryable: bool


class CatalogTableListResponse(BaseModel):
    items: list[CatalogTableItem] = Field(default_factory=list)


class CatalogColumnItem(BaseModel):
    name: str
    type: str
    description: str
    queryable: bool


class CatalogColumnListResponse(BaseModel):
    table: str
    columns: list[CatalogColumnItem] = Field(default_factory=list)
