from fastapi import APIRouter

from app.agent.workflow import DataAnalysisAgent
from app.schemas.chat import ChatRequest, ChatResponse


def create_chat_router(agent: DataAnalysisAgent) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["chat"])

    @router.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        result = agent.run(request.question)
        return ChatResponse(
            question=request.question,
            sql=result.get("sql", ""),
            sql_explanation=result.get("sql_explanation", ""),
            data=result.get("data", []),
            answer=result.get("answer", ""),
            error=result.get("error"),
        )

    return router
