from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import (
    DEFAULT_DATABASE_PATH,
    EMBEDDING_MODEL,
    KNOWLEDGE_TOP_K,
    QDRANT_COLLECTION,
    QDRANT_PATH,
)
from app.db.database import SQLiteDatabase
from app.services.knowledge import (
    BGEEmbedder,
    EMBEDDING_MODEL_NAME,
    QdrantKnowledgeBase,
    collect_knowledge_documents,
)


def main() -> int:
    if EMBEDDING_MODEL != EMBEDDING_MODEL_NAME:
        print("索引重建失败：Embedding 模型配置错误", file=sys.stderr)
        return 1

    try:
        db = SQLiteDatabase(DEFAULT_DATABASE_PATH)
        db.initialize()
        documents = collect_knowledge_documents(db)
        knowledge = QdrantKnowledgeBase(
            QDRANT_PATH,
            QDRANT_COLLECTION,
            BGEEmbedder(EMBEDDING_MODEL),
            KNOWLEDGE_TOP_K,
        )
        counts = knowledge.rebuild(documents)
    except Exception as exc:
        print(f"索引重建失败：{type(exc).__name__}", file=sys.stderr)
        return 1

    for knowledge_type in ("schema", "metric", "trusted_sql", "historical_qa"):
        print(f"{knowledge_type}: {counts.get(knowledge_type, 0)}")
    print(f"total: {sum(counts.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
