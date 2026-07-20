from pathlib import Path
from typing import cast

from fastapi import FastAPI

from app.agent.workflow import DataAnalysisAgent, KnowledgeRetriever
from app.api.routes import create_chat_router
from app.core.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT_SECONDS,
    DEFAULT_DATABASE_PATH,
    EMBEDDING_MODEL,
    KNOWLEDGE_TOP_K,
    META_DATABASE_URL,
    META_DB_TYPE,
    QDRANT_COLLECTION,
    QDRANT_PATH,
)
from app.db.database import SQLiteDatabase
from app.db.meta_mysql import MySQLMetaDatabase
from app.schemas.chat import HealthResponse
from app.services.knowledge import BGEEmbedder, QdrantKnowledgeBase
from app.services.llm import BaseLLMClient, DeepSeekLLMClient, UnavailableLLMClient


_AUTO = object()


def create_app(
    database_path: str | Path | None = None,
    llm: BaseLLMClient | None = None,
    knowledge: KnowledgeRetriever | None | object = _AUTO,
) -> FastAPI:
    db = _create_database(database_path or DEFAULT_DATABASE_PATH)
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

    if knowledge is _AUTO:
        try:
            knowledge_client: KnowledgeRetriever | None = QdrantKnowledgeBase(
                path=QDRANT_PATH,
                collection_name=QDRANT_COLLECTION,
                embedder=BGEEmbedder(EMBEDDING_MODEL),
                top_k=KNOWLEDGE_TOP_K,
            )
        except ValueError:
            knowledge_client = None
    else:
        knowledge_client = cast(KnowledgeRetriever | None, knowledge)
    agent = DataAnalysisAgent(db=db, llm=llm_client, knowledge=knowledge_client)

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


def _create_database(database_path: str | Path) -> SQLiteDatabase:
    if META_DB_TYPE == "sqlite":
        return SQLiteDatabase(database_path)
    if META_DB_TYPE == "mysql":
        if not META_DATABASE_URL:
            raise ValueError("META_DB_TYPE=mysql 时必须配置 META_DATABASE_URL")
        return MySQLMetaDatabase(META_DATABASE_URL, database_path)
    raise ValueError("META_DB_TYPE 只支持 sqlite 或 mysql")


app = create_app()
