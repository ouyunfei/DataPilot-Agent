import hashlib
import importlib
import os
import sqlite3
import subprocess
import sys
from types import ModuleType

import pytest
from qdrant_client import QdrantClient

from app.db.database import SQLiteDatabase
import app.services.knowledge as knowledge_module
from app.services.knowledge import (
    BGEEmbedder,
    EMBEDDING_DIMENSION,
    MAX_CONTEXT_CHARS,
    MAX_ITEM_CHARS,
    QUERY_INSTRUCTION,
    KnowledgeDocument,
    QdrantKnowledgeBase,
    _validated_vector,
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


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_vector_validation_rejects_non_finite_values(value):
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[0] = value

    with pytest.raises(ValueError, match="有限"):
        _validated_vector(vector)


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


def test_rebuild_rejects_non_finite_vector_before_replacing_collection(tmp_path):
    path = tmp_path / "non-finite-rebuild"
    knowledge = QdrantKnowledgeBase(path, "knowledge", FakeEmbedder(), top_k=5)
    knowledge.rebuild([_document(1, "old", "销售额指标定义")])

    class NonFiniteDocumentEmbedder(FakeEmbedder):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            vectors = super().embed_documents(texts)
            vectors[0][0] = float("nan")
            return vectors

    knowledge.embedder = NonFiniteDocumentEmbedder()

    with pytest.raises(ValueError, match="有限"):
        knowledge.rebuild([_document(1, "new", "新的销售额定义")])

    assert _count(path, "knowledge") == 1
    assert [hit["source_id"] for hit in knowledge.search("销售额", 1)] == ["old"]


def test_search_rejects_non_finite_query_vector(tmp_path):
    knowledge = QdrantKnowledgeBase(
        tmp_path / "non-finite-query", "knowledge", FakeEmbedder(), top_k=5
    )
    knowledge.rebuild([_document(1, "sales", "销售额指标定义")])

    class NonFiniteQueryEmbedder(FakeEmbedder):
        def embed_query(self, text: str) -> list[float]:
            vector = super().embed_query(text)
            vector[0] = float("inf")
            return vector

    knowledge.embedder = NonFiniteQueryEmbedder()

    with pytest.raises(ValueError, match="有限"):
        knowledge.search("销售额", 1)


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


def test_retrieve_skips_oversized_hit_and_includes_later_hit(tmp_path):
    knowledge = QdrantKnowledgeBase(
        path=tmp_path / "oversized",
        collection_name="oversized",
        embedder=FakeEmbedder(),
        top_k=5,
    )
    knowledge.rebuild(
        [
            KnowledgeDocument(
                data_source_id=1,
                knowledge_type="metric",
                source_id="oversized",
                title="超" * MAX_CONTEXT_CHARS,
                content="销售额",
            ),
            _document(1, "normal", "订单指标定义"),
        ]
    )

    context, sources = knowledge.retrieve("销售额", data_source_id=1)

    assert "normal" in context
    assert [source["source_id"] for source in sources] == ["normal"]
    assert len(context) <= MAX_CONTEXT_CHARS


def test_retrieve_returns_empty_context_and_sources_without_hits(tmp_path):
    knowledge = QdrantKnowledgeBase(
        tmp_path / "missing", "missing", FakeEmbedder(), top_k=5
    )

    assert knowledge.retrieve("销售额", data_source_id=1) == ("", [])


def test_collects_all_four_knowledge_types_without_database_secrets(tmp_path):
    db = SQLiteDatabase(tmp_path / "knowledge.db")
    db.initialize()
    source_id = db.get_default_data_source()["id"]
    db.log_query(
        question="销售额是多少？",
        sql="SELECT SUM(amount) FROM orders",
        trusted_answer=False,
        chart_type="",
        row_count=1,
        error=None,
        duration_ms=10,
        data_source_id=source_id,
        sql_explanation="汇总订单金额。",
        answer="销售额为 100 万元。",
    )
    log_id = db.list_query_logs()[0]["id"]
    db.update_query_feedback(log_id, feedback="like")

    documents = knowledge_module.collect_knowledge_documents(db)

    assert {document.knowledge_type for document in documents} == {
        "schema",
        "metric",
        "trusted_sql",
        "historical_qa",
    }
    assert all(document.data_source_id == source_id for document in documents)
    historical = next(
        document
        for document in documents
        if document.knowledge_type == "historical_qa"
    )
    assert historical.source_id == str(log_id)
    assert historical.content == (
        "问题：销售额是多少？\n"
        "SQL：SELECT SUM(amount) FROM orders\n"
        "解释：汇总订单金额。\n"
        "回答：销售额为 100 万元。"
    )
    for document in documents:
        assert str(db.path) not in document.content
        assert str(db.path) not in repr(document.payload)
        assert "database_url" not in document.payload


def test_collects_queryability_for_all_sqlite_schema_objects(tmp_path):
    database_path = tmp_path / "knowledge.db"
    db = SQLiteDatabase(database_path)
    db.initialize()
    source = db.create_data_source(
        name="orders_only",
        db_type="sqlite",
        database_url=str(database_path),
        allowed_tables=["orders"],
        allowed_columns={"orders": ["id", "amount"]},
    )

    documents = {
        document.source_id: document
        for document in knowledge_module.collect_knowledge_documents(db)
        if document.data_source_id == source["id"]
        and document.knowledge_type == "schema"
    }

    assert documents["table:products"].queryable is False
    assert documents["column:orders.amount"].queryable is True
    assert documents["column:orders.status"].queryable is False
    assert "标识：table:products" in documents["table:products"].content
    assert "可查询：否" in documents["table:products"].content
    assert "可查询：是" in documents["column:orders.amount"].content


def test_skips_metric_without_source_ownership_for_custom_sqlite(tmp_path):
    db = SQLiteDatabase(tmp_path / "knowledge.db")
    db.initialize()
    source_path = tmp_path / "inventory.db"
    with sqlite3.connect(source_path) as connection:
        connection.execute(
            "CREATE TABLE inventory (id INTEGER PRIMARY KEY, quantity INTEGER)"
        )
    source = db.create_data_source(
        name="inventory",
        db_type="sqlite",
        database_url=str(source_path),
        allowed_tables=["inventory"],
        allowed_columns={"inventory": ["id", "quantity"]},
    )

    metrics = [
        document.title
        for document in knowledge_module.collect_knowledge_documents(db)
        if document.data_source_id == source["id"]
        and document.knowledge_type == "metric"
    ]

    assert "退款率" not in metrics


def test_trusted_sql_requires_sqlite_and_current_whitelist(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "knowledge.db"
    db = SQLiteDatabase(database_path)
    db.initialize()
    source = db.get_default_data_source()
    db.update_data_source(
        source["id"],
        allowed_tables=["orders"],
        allowed_columns={"orders": ["id", "amount"]},
    )
    mysql_source = db.create_data_source(
        name="mysql",
        db_type="mysql",
        database_url="mysql://user:secret@localhost:3306/datapilot",
        allowed_tables=["orders"],
        allowed_columns={"orders": ["id", "amount"]},
    )
    monkeypatch.setattr(
        knowledge_module,
        "TRUSTED_ANSWERS",
        {
            "有效问题": {
                "sql": "SELECT amount FROM orders",
                "sql_explanation": "读取订单金额。",
            },
            "越权字段": {
                "sql": "SELECT status FROM orders",
                "sql_explanation": "读取订单状态。",
            },
            "越权表": {
                "sql": "SELECT id FROM products",
                "sql_explanation": "读取商品。",
            },
        },
    )
    original_list_catalog_tables = db.list_catalog_tables

    def list_catalog_tables(data_source_id=None, include_non_queryable=False):
        if data_source_id == mysql_source["id"]:
            return []
        return original_list_catalog_tables(data_source_id, include_non_queryable)

    monkeypatch.setattr(db, "list_catalog_tables", list_catalog_tables)
    metric_calls = 0
    original_list_metrics = db.list_metrics

    def list_metrics(enabled_only=False):
        nonlocal metric_calls
        metric_calls += 1
        return original_list_metrics(enabled_only)

    monkeypatch.setattr(db, "list_metrics", list_metrics)

    documents = knowledge_module.collect_knowledge_documents(db)
    trusted = [
        document
        for document in documents
        if document.knowledge_type == "trusted_sql"
    ]

    assert metric_calls == 1
    assert all(
        "mysql://user:secret@localhost:3306/datapilot" not in repr(document.payload)
        for document in documents
    )
    assert [(document.data_source_id, document.source_id) for document in trusted] == [
        (
            source["id"],
            hashlib.sha256("有效问题".encode()).hexdigest()[:16],
        )
    ]
    assert "SELECT amount FROM orders LIMIT 100" in trusted[0].content
    assert "引用表：orders" in trusted[0].content
    assert "引用字段：amount" in trusted[0].content


def test_trusted_sql_field_references_exclude_projection_aliases(tmp_path):
    db = SQLiteDatabase(tmp_path / "knowledge.db")
    db.initialize()

    trusted = next(
        document
        for document in knowledge_module.collect_knowledge_documents(db)
        if document.knowledge_type == "trusted_sql"
        and document.title == "最近30天销售额最高的5个商品是什么"
    )

    assert trusted.content.splitlines()[-1] == (
        "引用字段：amount、created_at、product_name、status"
    )


@pytest.mark.parametrize(
    "sql", ["SELECT product_name FROM products", "SELECT status FROM orders"]
)
def test_skips_liked_history_outside_current_source_whitelist(tmp_path, sql):
    db = SQLiteDatabase(tmp_path / "knowledge.db")
    db.initialize()
    source = db.get_default_data_source()
    db.log_query(
        question="旧查询",
        sql=sql,
        trusted_answer=False,
        chart_type="",
        row_count=1,
        error=None,
        duration_ms=10,
        data_source_id=source["id"],
        sql_explanation="使用旧白名单查询。",
        answer="旧查询结果。",
    )
    log_id = db.list_query_logs()[0]["id"]
    db.update_query_feedback(log_id, feedback="like")
    db.update_data_source(
        source["id"],
        allowed_tables=["orders"],
        allowed_columns={"orders": ["id", "amount"]},
    )

    historical = [
        document
        for document in knowledge_module.collect_knowledge_documents(db)
        if document.knowledge_type == "historical_qa"
    ]

    assert historical == []


def test_rebuild_script_collects_before_replacing_index(monkeypatch, capsys):
    rebuild = importlib.import_module("scripts.rebuild_knowledge_index")
    config = importlib.import_module("app.core.config")
    database = importlib.import_module("app.db.database")
    events = []
    documents = [_document(1, "sales", "销售额指标定义")]

    class FakeDatabase:
        def __init__(self, path):
            events.append(("database", path))

        def initialize(self):
            events.append("initialize")

    class FakeBGEEmbedder:
        def __init__(self, model_name):
            events.append(("embedder", model_name))

    class FakeKnowledgeBase:
        def __init__(self, path, collection_name, embedder, top_k):
            events.append(("knowledge", path, collection_name, embedder, top_k))

        def rebuild(self, received_documents):
            assert received_documents == documents
            events.append("rebuild")
            return {"metric": 1}

    def collect(db):
        assert isinstance(db, FakeDatabase)
        events.append("collect")
        return documents

    monkeypatch.setattr(database, "SQLiteDatabase", FakeDatabase)
    monkeypatch.setattr(knowledge_module, "BGEEmbedder", FakeBGEEmbedder)
    monkeypatch.setattr(knowledge_module, "QdrantKnowledgeBase", FakeKnowledgeBase)
    monkeypatch.setattr(knowledge_module, "collect_knowledge_documents", collect)
    monkeypatch.setattr(
        config, "EMBEDDING_MODEL", knowledge_module.EMBEDDING_MODEL_NAME
    )

    assert rebuild.main() == 0

    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "schema: 0",
        "metric: 1",
        "trusted_sql: 0",
        "historical_qa: 0",
        "total: 1",
    ]
    assert events[0][0] == "database"
    assert events[1:3] == ["initialize", "collect"]
    assert events[-1] == "rebuild"


def test_rebuild_script_hides_exception_details(monkeypatch, capsys):
    rebuild = importlib.import_module("scripts.rebuild_knowledge_index")
    config = importlib.import_module("app.core.config")
    database = importlib.import_module("app.db.database")

    class FailingDatabase:
        def __init__(self, _path):
            pass

        def initialize(self):
            raise RuntimeError("mysql://user:password@host/private.db")

    monkeypatch.setattr(database, "SQLiteDatabase", FailingDatabase)
    monkeypatch.setattr(
        config, "EMBEDDING_MODEL", knowledge_module.EMBEDDING_MODEL_NAME
    )

    assert rebuild.main() == 1

    stdout, stderr = capsys.readouterr()
    assert stdout == ""
    assert stderr == "索引重建失败：RuntimeError\n"


def test_rebuild_script_rejects_other_embedding_model_without_loading(
    monkeypatch, capsys
):
    rebuild = importlib.import_module("scripts.rebuild_knowledge_index")
    config = importlib.import_module("app.core.config")
    database = importlib.import_module("app.db.database")

    class UnexpectedDatabase:
        def __init__(self, _path):
            raise AssertionError("database must not load")

    monkeypatch.setattr(database, "SQLiteDatabase", UnexpectedDatabase)
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "other/model")

    assert rebuild.main() == 1

    stdout, stderr = capsys.readouterr()
    assert stdout == ""
    assert stderr == "索引重建失败：Embedding 模型配置错误\n"


def test_rebuild_script_hides_config_import_errors(tmp_path):
    env = os.environ | {
        "KNOWLEDGE_TOP_K": "not-an-int",
        "QDRANT_PATH": str(tmp_path / "private-password-index"),
        "DEEPSEEK_BASE_URL": "https://user:password@example.com",
    }

    result = subprocess.run(
        [sys.executable, "scripts/rebuild_knowledge_index.py"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "索引重建失败：ValueError\n"
    assert "Traceback" not in result.stderr
    assert str(tmp_path) not in result.stderr
    assert "password" not in result.stderr
