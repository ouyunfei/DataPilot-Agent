import sys
from types import ModuleType

import pytest
from qdrant_client import QdrantClient

from app.services.knowledge import (
    BGEEmbedder,
    EMBEDDING_DIMENSION,
    MAX_CONTEXT_CHARS,
    MAX_ITEM_CHARS,
    QUERY_INSTRUCTION,
    KnowledgeDocument,
    QdrantKnowledgeBase,
)


class FakeEmbedder:
    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    @staticmethod
    def _vector(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSION
        vector[0 if "销售" in text else 1] = 1.0
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return self._vector(text)


def _document(
    data_source_id: int,
    source_id: str,
    content: str,
    *,
    queryable: bool = True,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        data_source_id=data_source_id,
        knowledge_type="metric",
        source_id=source_id,
        title=source_id,
        content=content,
        queryable=queryable,
    )


def _count(path, collection_name: str) -> int:
    client = QdrantClient(path=str(path))
    try:
        return client.count(collection_name, exact=True).count
    finally:
        client.close()


def test_knowledge_document_has_stable_source_scoped_point_id():
    first = _document(1, "sales", "销售额指标定义")
    same = _document(1, "sales", "修改后的内容")
    other_source = _document(2, "sales", "销售额指标定义")

    assert first.point_id == same.point_id
    assert first.point_id != other_source.point_id


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"data_source_id": 0}, "data_source_id"),
        ({"knowledge_type": "other"}, "knowledge_type"),
        ({"source_id": " "}, "不能为空"),
        ({"title": " "}, "不能为空"),
        ({"content": " "}, "不能为空"),
    ],
)
def test_knowledge_document_rejects_invalid_values(overrides, message):
    values = {
        "data_source_id": 1,
        "knowledge_type": "schema",
        "source_id": "orders",
        "title": "订单表",
        "content": "订单表说明",
    }

    with pytest.raises(ValueError, match=message):
        KnowledgeDocument(**(values | overrides))


def test_knowledge_payload_contains_only_safe_metadata():
    document = _document(1, "sales", "销售额指标定义")

    assert document.payload == {
        "data_source_id": 1,
        "knowledge_type": "metric",
        "source_id": "sales",
        "title": "sales",
        "content": "销售额指标定义",
        "queryable": True,
    }
    assert "database_url" not in document.payload
    assert "vector" not in document.payload


def test_bge_embedder_rejects_other_models_without_loading_model(monkeypatch):
    module = ModuleType("sentence_transformers")

    class UnexpectedModel:
        def __init__(self, _model_name: str) -> None:
            raise AssertionError("model must not load")

    module.SentenceTransformer = UnexpectedModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    with pytest.raises(ValueError, match="BAAI/bge-small-zh-v1.5"):
        BGEEmbedder("other/model")


def test_bge_embedder_loads_lazily_and_encodes_documents_and_instructed_queries(monkeypatch):
    module = ModuleType("sentence_transformers")
    loaded_models: list[str] = []
    encode_calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str) -> None:
            loaded_models.append(model_name)

        def encode(self, texts: list[str], **kwargs):
            encode_calls.append((texts, kwargs))
            return [[1.0] + [0.0] * (EMBEDDING_DIMENSION - 1) for _ in texts]

    module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    embedder = BGEEmbedder()

    assert loaded_models == []
    assert embedder.embed_documents(["订单表"]) == [
        [1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)
    ]
    assert embedder.embed_query("销售额") == [1.0] + [0.0] * (
        EMBEDDING_DIMENSION - 1
    )
    assert loaded_models == ["BAAI/bge-small-zh-v1.5"]
    assert encode_calls[0] == (
        ["订单表"],
        {"normalize_embeddings": True, "convert_to_numpy": True},
    )
    assert encode_calls[1][0] == [f"{QUERY_INSTRUCTION}销售额"]
    assert encode_calls[1][1]["normalize_embeddings"] is True


def test_bge_embedder_rejects_wrong_vector_dimension(monkeypatch):
    module = ModuleType("sentence_transformers")

    class WrongDimensionModel:
        def __init__(self, _model_name: str) -> None:
            pass

        def encode(self, texts: list[str], **_kwargs):
            return [[1.0, 0.0] for _ in texts]

    module.SentenceTransformer = WrongDimensionModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    with pytest.raises(ValueError, match="512"):
        BGEEmbedder().embed_query("销售额")


def test_qdrant_local_rebuild_is_idempotent_and_searchable(tmp_path):
    path = tmp_path / "qdrant"
    embedder = FakeEmbedder()
    knowledge = QdrantKnowledgeBase(
        path=path,
        collection_name="test_knowledge",
        embedder=embedder,
        top_k=5,
    )
    documents = [_document(1, "sales", "销售额指标定义")]

    first = knowledge.rebuild(documents)
    second = knowledge.rebuild(documents)
    hits = knowledge.search("销售额", data_source_id=1)

    assert first == {"metric": 1}
    assert second == first
    assert _count(path, "test_knowledge") == 1
    assert hits == [
        {
            "knowledge_type": "metric",
            "source_id": "sales",
            "title": "sales",
            "content": "销售额指标定义",
            "score": pytest.approx(1.0),
        }
    ]


def test_qdrant_search_isolated_by_data_source(tmp_path):
    knowledge = QdrantKnowledgeBase(
        path=tmp_path / "isolated",
        collection_name="isolated",
        embedder=FakeEmbedder(),
        top_k=5,
    )
    knowledge.rebuild(
        [
            _document(1, "source-1", "销售额指标定义"),
            _document(2, "source-2", "销售额指标定义"),
        ]
    )

    hits = knowledge.search("销售额", data_source_id=2)

    assert [hit["source_id"] for hit in hits] == ["source-2"]


def test_qdrant_search_never_recalls_non_queryable_document(tmp_path):
    knowledge = QdrantKnowledgeBase(
        path=tmp_path / "queryable",
        collection_name="queryable",
        embedder=FakeEmbedder(),
        top_k=5,
    )
    knowledge.rebuild([_document(1, "hidden", "销售额指标定义", queryable=False)])

    assert knowledge.search("销售额", data_source_id=1) == []


def test_missing_path_does_not_call_query_embedder(tmp_path):
    embedder = FakeEmbedder()
    path = tmp_path / "missing"
    knowledge = QdrantKnowledgeBase(path, "missing", embedder, top_k=5)

    assert knowledge.search("销售额", data_source_id=1) == []
    assert embedder.query_calls == 0
    assert not path.exists()


def test_missing_collection_does_not_call_query_embedder(tmp_path):
    embedder = FakeEmbedder()
    path = tmp_path / "missing-collection"
    path.mkdir()
    knowledge = QdrantKnowledgeBase(path, "missing", embedder, top_k=5)

    assert knowledge.search("销售额", data_source_id=1) == []
    assert embedder.query_calls == 0


def test_empty_rebuild_creates_empty_collection(tmp_path):
    path = tmp_path / "empty"
    knowledge = QdrantKnowledgeBase(path, "empty", FakeEmbedder(), top_k=5)

    assert knowledge.rebuild([]) == {}
    assert _count(path, "empty") == 0


def test_rebuild_validates_embedding_count_before_replacing_collection(tmp_path):
    path = tmp_path / "bad-count"
    knowledge = QdrantKnowledgeBase(path, "knowledge", FakeEmbedder(), top_k=5)
    knowledge.rebuild([_document(1, "old", "销售额指标定义")])

    class MissingVectorEmbedder(FakeEmbedder):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return []

    knowledge.embedder = MissingVectorEmbedder()

    with pytest.raises(ValueError, match="数量"):
        knowledge.rebuild([_document(1, "new", "新的销售额定义")])

    assert _count(path, "knowledge") == 1


def test_rebuild_validates_embedding_dimension_before_replacing_collection(tmp_path):
    path = tmp_path / "bad-dimension"
    knowledge = QdrantKnowledgeBase(path, "knowledge", FakeEmbedder(), top_k=5)
    knowledge.rebuild([_document(1, "old", "销售额指标定义")])

    class WrongDimensionEmbedder(FakeEmbedder):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    knowledge.embedder = WrongDimensionEmbedder()

    with pytest.raises(ValueError, match="512"):
        knowledge.rebuild([_document(1, "new", "新的销售额定义")])

    assert _count(path, "knowledge") == 1


def test_retrieve_limits_context_and_minimizes_sources(tmp_path):
    knowledge = QdrantKnowledgeBase(
        path=tmp_path / "context",
        collection_name="context",
        embedder=FakeEmbedder(),
        top_k=5,
    )
    knowledge.rebuild(
        [
            _document(1, str(index), "销售" + "额" * 2000)
            for index in range(5)
        ]
    )

    context, sources = knowledge.retrieve("销售额", data_source_id=1)
    blocks = context.split("\n\n")

    assert "参考知识" in blocks[0]
    assert "安全" in blocks[0]
    assert "Schema" in blocks[0]
    assert "SQL 校验" in blocks[0]
    assert len(context) <= MAX_CONTEXT_CHARS
    assert len(blocks) - 1 == len(sources)
    assert all(len(block.split("\n", 1)[1]) <= MAX_ITEM_CHARS for block in blocks[1:])
    assert all(
        set(source) == {"knowledge_type", "source_id", "title", "score"}
        for source in sources
    )


def test_retrieve_returns_empty_context_and_sources_without_hits(tmp_path):
    knowledge = QdrantKnowledgeBase(
        tmp_path / "missing", "missing", FakeEmbedder(), top_k=5
    )

    assert knowledge.retrieve("销售额", data_source_id=1) == ("", [])
