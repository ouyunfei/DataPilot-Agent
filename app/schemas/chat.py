from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户的自然语言数据分析问题")


class ChatResponse(BaseModel):
    question: str
    sql: str = ""
    sql_explanation: str = ""
    data: list[dict[str, Any]] = Field(default_factory=list)
    answer: str = ""
    error: str | None = None
