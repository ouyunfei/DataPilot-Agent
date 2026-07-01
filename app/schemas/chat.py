from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户的自然语言数据分析问题")
    session_id: str | None = Field(default=None, description="多轮追问会话 ID")


class ChatResponse(BaseModel):
    question: str
    session_id: str = ""
    sql: str = ""
    sql_explanation: str = ""
    data: list[dict[str, Any]] = Field(default_factory=list)
    chart: dict[str, Any] = Field(default_factory=dict)
    trusted_answer: bool = False
    answer: str = ""
    error: str | None = None


class QueryLogItem(BaseModel):
    id: int
    question: str
    sql: str
    trusted_answer: bool
    chart_type: str
    row_count: int
    error: str | None = None
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
    top_questions: list[TopQuestionItem] = Field(default_factory=list)


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
    forbidden_keywords: list[str]
    max_limit: int
