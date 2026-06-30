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
from app.schemas.chat import HealthResponse
from app.services.llm import BaseLLMClient, DeepSeekLLMClient, UnavailableLLMClient


def create_app(database_path: str | Path | None = None, llm: BaseLLMClient | None = None) -> FastAPI:
    db = SQLiteDatabase(database_path or DEFAULT_DATABASE_PATH)
    db.initialize()

    if llm is not None:
        llm_client = llm
    elif _deepseek_configured():
        llm_client = DeepSeekLLMClient(
            api_key=DEEPSEEK_API_KEY,
            model=DEEPSEEK_MODEL,
            base_url=DEEPSEEK_BASE_URL,
            timeout_seconds=DEEPSEEK_TIMEOUT_SECONDS,
        )
    else:
        llm_client = UnavailableLLMClient("缺少 DEEPSEEK_API_KEY，请在 .env 或环境变量中配置。")
    agent = DataAnalysisAgent(db=db, llm=llm_client)

    app = FastAPI(
        title="DataPilot Agent",
        description="基于 LangGraph 的智能数据分析 Agent 后端 MVP",
        version="0.1.0",
    )
    app.include_router(create_chat_router(agent))

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        try:
            table_count = len(db.list_tables())
            database_status = "ok"
        except Exception:
            table_count = 0
            database_status = "error"

        return HealthResponse(
            status="ok" if database_status == "ok" else "error",
            database_status=database_status,
            deepseek_configured=_deepseek_configured(),
            table_count=table_count,
        )

    return app


def _deepseek_configured() -> bool:
    return bool(DEEPSEEK_API_KEY and DEEPSEEK_API_KEY != "your_deepseek_api_key")


app = create_app()
