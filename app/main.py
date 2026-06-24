from pathlib import Path

from fastapi import FastAPI

from app.agent.workflow import DataAnalysisAgent
from app.api.routes import create_chat_router
from app.core.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT_SECONDS,
    DEFAULT_DATABASE_PATH,
)
from app.db.database import SQLiteDatabase
from app.services.llm import BaseLLMClient, DeepSeekLLMClient


def create_app(database_path: str | Path | None = None, llm: BaseLLMClient | None = None) -> FastAPI:
    db = SQLiteDatabase(database_path or DEFAULT_DATABASE_PATH)
    db.initialize()

    llm_client = llm or DeepSeekLLMClient(
        api_key=DEEPSEEK_API_KEY,
        model=DEEPSEEK_MODEL,
        base_url=DEEPSEEK_BASE_URL,
        timeout_seconds=DEEPSEEK_TIMEOUT_SECONDS,
    )
    agent = DataAnalysisAgent(db=db, llm=llm_client)

    app = FastAPI(
        title="DataPilot Agent",
        description="基于 LangGraph 的智能数据分析 Agent 后端 MVP",
        version="0.1.0",
    )
    app.include_router(create_chat_router(agent))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
