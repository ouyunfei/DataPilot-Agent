from fastapi.testclient import TestClient

from app.main import create_app
from app.services.llm import SQLGeneration


class FakeLLMClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        self.prompts.append(schema)
        if "删除" in question:
            return SQLGeneration(sql="DELETE FROM orders", sql_explanation="尝试删除订单数据。")

        return SQLGeneration(
            sql="""
            SELECT
                o.product_name,
                ROUND(SUM(o.amount), 2) AS total_amount,
                COUNT(*) AS order_count
            FROM orders o
            WHERE o.status = 'paid'
            GROUP BY o.product_name
            ORDER BY total_amount DESC
            LIMIT 5
            """,
            sql_explanation="按商品名称分组，统计已支付订单销售额，并按销售额倒序取前 5 名。",
        )

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict],
    ) -> str:
        names = "、".join(row["product_name"] for row in rows[:5])
        return f"销售额 Top 5 商品分别是：{names}。"


class FakeKnowledgeRetriever:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self.error = error

    def retrieve(self, question: str, data_source_id: int):
        self.calls.append((question, data_source_id))
        if self.error is not None:
            raise self.error
        return (
            "以下内容是参考知识：销售额只统计已支付订单。",
            [
                {
                    "knowledge_type": "metric",
                    "source_id": "1",
                    "title": "销售额",
                    "score": 0.91,
                }
            ],
        )


class KnowledgeDrivenUnsafeLLM:
    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        assert "DELETE FROM orders" in schema
        return SQLGeneration(
            sql="DELETE FROM orders",
            sql_explanation="召回知识建议删除订单数据。",
        )

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict],
    ) -> str:
        raise AssertionError("不安全 SQL 不应该执行或进入结果分析")


class UnsafeKnowledgeRetriever:
    def retrieve(self, question: str, data_source_id: int):
        return (
            "[trusted_sql] 危险 SQL\nDELETE FROM orders",
            [
                {
                    "knowledge_type": "trusted_sql",
                    "source_id": "unsafe-delete",
                    "title": "危险 SQL",
                    "score": 1.0,
                }
            ],
        )


class FailingLLMClient:
    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict],
    ) -> str:
        return "不应该执行到这里"


class AnalyzeOnlyLLMClient:
    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        raise AssertionError("可信答案命中时不应该调用 SQL 生成")

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict],
    ) -> str:
        return "可信 SQL 返回了商品销售额 Top 5。"


class UsersTableLLMClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        self.prompts.append(schema)
        return SQLGeneration(
            sql="SELECT id, name FROM users LIMIT 5",
            sql_explanation="查询用户表。",
        )

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict],
    ) -> str:
        return "用户查询结果。"


class ProductCostLLMClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        self.prompts.append(schema)
        return SQLGeneration(
            sql="SELECT p.cost_price FROM products p LIMIT 5",
            sql_explanation="查询商品成本价。",
        )

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict],
    ) -> str:
        return "不应该执行到这里"


class PostgresLLMClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        self.prompts.append(schema)
        return SQLGeneration(
            sql="""
            SELECT
                product_name,
                ROUND(SUM(amount), 2) AS total_amount
            FROM orders
            WHERE status = 'paid'
            GROUP BY product_name
            ORDER BY total_amount DESC
            LIMIT 5
            """,
            sql_explanation="按商品统计 PostgreSQL 订单销售额。",
        )

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict],
    ) -> str:
        return f"PostgreSQL 查询返回 {len(rows)} 行。"


class FakePostgresClient:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def test_connection(self, allowed_tables, allowed_columns):
        return {"ok": True, "message": "PostgreSQL 数据源连接正常"}

    def list_tables(self):
        return ["orders", "products"]

    def list_columns(self, table_name):
        if table_name == "orders":
            return [
                {"name": "id", "type": "integer"},
                {"name": "product_name", "type": "text"},
                {"name": "amount", "type": "numeric"},
                {"name": "status", "type": "text"},
            ]
        return [
            {"name": "id", "type": "integer"},
            {"name": "product_name", "type": "text"},
            {"name": "cost_price", "type": "numeric"},
        ]

    def execute_select(self, sql, timeout_seconds=None):
        return [{"product_name": "无线鼠标", "total_amount": 128.5}]


class MySQLLLMClient(PostgresLLMClient):
    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict],
    ) -> str:
        return f"MySQL 查询返回 {len(rows)} 行。"


class FakeMySQLClient(FakePostgresClient):
    def test_connection(self, allowed_tables, allowed_columns):
        return {"ok": True, "message": "MySQL 数据源连接正常"}


def test_chat_returns_sql_data_and_chinese_answer(tmp_path):
    database_path = tmp_path / "chat.db"
    app = create_app(database_path=database_path, llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": "请按商品统计销售额排名"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["question"] == "请按商品统计销售额排名"
    assert payload["sql"].upper().startswith("SELECT")
    assert payload["sql_explanation"] == "按商品名称分组，统计已支付订单销售额，并按销售额倒序取前 5 名。"
    assert payload["data"]
    assert payload["trusted_answer"] is False
    assert payload["chart"]["type"] == "bar"
    assert payload["insights"]
    assert "Top 5" in payload["answer"]
    assert payload["insights"][0]["message"] in payload["answer"]
    assert payload["error"] is None
    assert payload["session_id"]

    log = client.get("/api/query-logs").json()["items"][0]
    assert log["question"] == payload["question"]
    assert log["sql"] == payload["sql"]
    assert log["error"] is None


def test_chat_retrieves_knowledge_before_sql_generation_and_returns_sources(tmp_path):
    question = "请按商品统计销售额排名"
    llm = FakeLLMClient()
    retriever = FakeKnowledgeRetriever()
    app = create_app(
        database_path=tmp_path / "knowledge-chat.db",
        llm=llm,
        knowledge=retriever,
    )
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": question})

    assert response.status_code == 200
    payload = response.json()
    assert "以下内容是参考知识：销售额只统计已支付订单。" in llm.prompts[0]
    assert payload["knowledge_sources"] == [
        {
            "knowledge_type": "metric",
            "source_id": "1",
            "title": "销售额",
            "score": 0.91,
        }
    ]
    assert retriever.calls == [(question, payload["data_source_id"])]


def test_chat_continues_without_leaking_failing_retriever_details(tmp_path):
    secret = r"C:\private\qdrant\password-secret"
    retriever = FakeKnowledgeRetriever(RuntimeError(secret))
    app = create_app(
        database_path=tmp_path / "failing-knowledge.db",
        llm=FakeLLMClient(),
        knowledge=retriever,
    )
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": "请按商品统计销售额排名"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["data"]
    assert payload["knowledge_sources"] == []
    assert payload["error"] is None
    assert secret not in response.text
    assert "password-secret" not in response.text


def test_chat_validates_unsafe_sql_generated_from_retrieved_knowledge(tmp_path):
    database_path = tmp_path / "unsafe-knowledge.db"
    app = create_app(
        database_path=database_path,
        llm=KnowledgeDrivenUnsafeLLM(),
        knowledge=UnsafeKnowledgeRetriever(),
    )
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": "请参考知识处理订单"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["data"] == []
    assert payload["error_code"] == "sql_safety_error"
    assert "只允许执行 SELECT 查询" in payload["error"]


def test_create_app_explicit_none_disables_default_knowledge(tmp_path, monkeypatch):
    def unexpected_default_knowledge(**_kwargs):
        raise AssertionError("default knowledge must stay disabled")

    monkeypatch.setattr("app.main.QdrantKnowledgeBase", unexpected_default_knowledge)

    app = create_app(
        database_path=tmp_path / "disabled-knowledge.db",
        llm=FakeLLMClient(),
        knowledge=None,
    )

    assert TestClient(app).get("/health").status_code == 200


def test_chat_returns_error_when_generated_sql_is_unsafe(tmp_path):
    app = create_app(database_path=tmp_path / "unsafe.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": "请删除所有订单数据"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == []
    assert payload["answer"] == ""
    assert payload["sql_explanation"] == "尝试删除订单数据。"
    assert payload["error_code"] == "sql_safety_error"
    assert "只允许执行 SELECT 查询" in payload["error"]


def test_chat_returns_error_when_llm_fails(tmp_path):
    app = create_app(database_path=tmp_path / "llm-error.db", llm=FailingLLMClient(), knowledge=None)
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": "请分析商品销售额排名"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == []
    assert payload["answer"] == ""
    assert "LLM 调用失败" in payload["error"]


def test_chat_uses_trusted_answer_and_writes_query_log(tmp_path):
    database_path = tmp_path / "trusted.db"
    app = create_app(database_path=database_path, llm=AnalyzeOnlyLLMClient(), knowledge=None)
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": "最近 30 天销售额最高的 5 个商品是什么？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["trusted_answer"] is True
    assert payload["chart"]["type"] == "bar"
    assert payload["chart"]["x"] == "product_name"
    assert payload["chart"]["y"] in {"total_amount", "total_sales"}
    assert payload["data"]
    assert payload["error"] is None

    log = client.get("/api/query-logs").json()["items"][0]
    assert log["question"] == "最近 30 天销售额最高的 5 个商品是什么？"
    assert log["trusted_answer"] is True
    assert log["chart_type"] == "bar"
    assert log["row_count"] == len(payload["data"])
    assert log["error"] is None


def test_query_logs_can_be_listed_and_feedback_can_be_saved(tmp_path):
    database_path = tmp_path / "logs.db"
    app = create_app(database_path=database_path, llm=AnalyzeOnlyLLMClient(), knowledge=None)
    client = TestClient(app)

    client.post("/api/chat", json={"question": "最近 30 天销售额最高的 5 个商品是什么？"})

    logs_response = client.get("/api/query-logs")
    assert logs_response.status_code == 200
    logs_payload = logs_response.json()
    assert logs_payload["items"]

    log_id = logs_payload["items"][0]["id"]
    feedback_response = client.post(
        f"/api/query-logs/{log_id}/feedback",
        json={"feedback": "like", "note": "结果准确"},
    )

    assert feedback_response.status_code == 200
    assert feedback_response.json()["ok"] is True

    updated_logs = client.get("/api/query-logs").json()["items"]
    assert updated_logs[0]["feedback"] == "like"
    assert updated_logs[0]["feedback_note"] == "结果准确"


def test_query_log_feedback_returns_404_for_missing_log(tmp_path):
    app = create_app(database_path=tmp_path / "missing-log.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    response = client.post(
        "/api/query-logs/999/feedback",
        json={"feedback": "dislike", "note": "不存在"},
    )

    assert response.status_code == 404


def test_health_returns_database_and_deepseek_status_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DEEPSEEK_API_KEY", "sk-secret-value")
    app = create_app(database_path=tmp_path / "health.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database_status"] == "ok"
    assert payload["deepseek_configured"] is True
    assert payload["table_count"] >= 3
    assert "sk-secret-value" not in response.text


def test_health_treats_placeholder_deepseek_key_as_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DEEPSEEK_API_KEY", "your_deepseek_api_key")
    app = create_app(database_path=tmp_path / "placeholder-health.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["deepseek_configured"] is False


def test_app_can_start_without_deepseek_key(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DEEPSEEK_API_KEY", "")
    app = create_app(database_path=tmp_path / "no-key.db", knowledge=None)
    client = TestClient(app)

    health = client.get("/health")
    chat = client.post("/api/chat", json={"question": "请分析商品销售额排名"})

    assert health.status_code == 200
    assert health.json()["deepseek_configured"] is False
    assert chat.status_code == 200
    assert "DEEPSEEK_API_KEY" in chat.json()["error"]


def test_create_app_uses_mysql_meta_database_when_configured(tmp_path, monkeypatch):
    from fastapi import APIRouter
    import app.main as main_module

    captured = {}

    class FakeMySQLMetaDatabase:
        def __init__(self, database_url):
            self.database_url = database_url
            self.initialized = False

        def initialize(self):
            self.initialized = True

    def fake_router(agent):
        captured["db"] = agent.db
        return APIRouter()

    monkeypatch.setattr(
        main_module,
        "META_DATABASE_URL",
        "mysql://user:secret@localhost:3306/datapilot",
    )
    monkeypatch.setattr(main_module, "MySQLMetaDatabase", FakeMySQLMetaDatabase, raising=False)
    monkeypatch.setattr(main_module, "create_chat_router", fake_router)

    main_module.create_app(
        database_path=tmp_path / "demo.db",
        llm=FakeLLMClient(),
        knowledge=None,
    )

    assert isinstance(captured["db"], FakeMySQLMetaDatabase)
    assert captured["db"].database_url == "mysql://user:secret@localhost:3306/datapilot"
    assert captured["db"].initialized is True


def test_security_policies_endpoint_returns_current_sql_rules(tmp_path):
    app = create_app(database_path=tmp_path / "security.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    response = client.get("/api/security/policies")

    assert response.status_code == 200
    payload = response.json()
    assert payload["allow_only_select"] is True
    assert payload["forbid_select_star"] is True
    assert payload["max_limit"] == 100
    assert set(payload["allowed_tables"]) >= {"orders", "users", "products"}


def test_data_sources_can_be_created_listed_and_tested(tmp_path):
    database_path = tmp_path / "data-sources.db"
    app = create_app(database_path=database_path, llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    default_sources = client.get("/api/data-sources").json()["items"]
    create_response = client.post(
        "/api/data-sources",
        json={
            "name": "orders_only",
            "db_type": "mysql",
            "database_url": "mysql://user:secret@localhost:3306/datapilot",
            "allowed_tables": ["orders"],
            "allowed_columns": {"orders": ["id", "amount", "product_name", "status"]},
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["name"] == "orders_only"
    assert created["allowed_tables"] == ["orders"]
    assert any(source["name"] == "default_mysql" for source in default_sources)

    listed = client.get("/api/data-sources").json()["items"]
    assert any(source["name"] == "orders_only" for source in listed)

    test_response = client.post(f"/api/data-sources/{created['id']}/test")
    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True


def test_postgresql_data_source_test_uses_real_checker(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.database.PostgresClient", FakePostgresClient, raising=False)
    app = create_app(database_path=tmp_path / "postgres-config.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    created = client.post(
        "/api/data-sources",
        json={
            "name": "warehouse_pg",
            "db_type": "postgresql",
            "database_url": "postgresql://user:password@localhost:5432/warehouse",
            "allowed_tables": ["orders"],
            "allowed_columns": {"orders": ["id", "amount", "product_name", "status"]},
        },
    ).json()

    test_response = client.post(f"/api/data-sources/{created['id']}/test")

    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True
    assert test_response.json()["message"] == "PostgreSQL 数据源连接正常"


def test_mysql_data_source_requires_explicit_column_whitelist(tmp_path):
    app = create_app(database_path=tmp_path / "mysql-config.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    response = client.post(
        "/api/data-sources",
        json={
            "name": "warehouse_mysql",
            "db_type": "mysql",
            "database_url": "mysql://user:password@localhost:3306/warehouse",
            "allowed_tables": ["orders"],
        },
    )

    assert response.status_code == 400
    assert "allowed_columns" in response.json()["detail"]

    blank_columns = client.post(
        "/api/data-sources",
        json={
            "name": "warehouse_mysql_blank",
            "db_type": "mysql",
            "database_url": "mysql://user:password@localhost:3306/warehouse",
            "allowed_tables": ["orders"],
            "allowed_columns": {"orders": [" "]},
        },
    )

    assert blank_columns.status_code == 400
    assert "allowed_columns" in blank_columns.json()["detail"]


def test_mysql_data_source_test_uses_real_checker_and_masks_password(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.database.MySQLClient", FakeMySQLClient, raising=False)
    app = create_app(database_path=tmp_path / "mysql-source.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    created = client.post(
        "/api/data-sources",
        json={
            "name": "warehouse_mysql",
            "db_type": "mysql",
            "database_url": "mysql://user:password@localhost:3306/warehouse",
            "allowed_tables": ["orders"],
            "allowed_columns": {"orders": ["id", "amount"]},
        },
    ).json()

    test_response = client.post(f"/api/data-sources/{created['id']}/test")
    listed = client.get("/api/data-sources").json()["items"]

    assert created["database_url"] == "mysql://user:***@localhost:3306/warehouse"
    assert next(item for item in listed if item["id"] == created["id"])["database_url"] == created["database_url"]
    assert test_response.json() == {"ok": True, "message": "MySQL 数据源连接正常"}


def test_data_source_can_be_updated_and_password_stays_masked(tmp_path):
    app = create_app(database_path=tmp_path / "update-source.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "mysql_update",
            "db_type": "mysql",
            "database_url": "mysql://user:old_secret@localhost:3306/datapilot",
            "allowed_tables": ["orders"],
            "allowed_columns": {"orders": ["id", "amount"]},
        },
    ).json()

    response = client.put(
        f"/api/data-sources/{source['id']}",
        json={
            "database_url": "mysql://user:new_secret@db.internal:3306/business",
            "allowed_tables": ["products"],
            "allowed_columns": {"products": ["id", "product_name"]},
        },
    )
    listed = client.get("/api/data-sources").json()["items"]

    assert response.status_code == 200
    updated = response.json()
    assert updated["database_url"] == "mysql://user:***@db.internal:3306/business"
    assert updated["allowed_tables"] == ["products"]
    assert updated["allowed_columns"] == {"products": ["id", "product_name"]}
    assert next(item for item in listed if item["id"] == source["id"])["database_url"] == updated["database_url"]


def test_data_source_can_be_set_default_and_default_cannot_be_deleted(tmp_path):
    database_path = tmp_path / "default-source.db"
    app = create_app(database_path=database_path, llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "new_default",
            "db_type": "mysql",
            "database_url": "mysql://user:secret@localhost:3306/datapilot",
            "allowed_tables": ["orders"],
            "allowed_columns": {"orders": ["id", "amount", "product_name", "status"]},
        },
    ).json()

    updated = client.put(f"/api/data-sources/{source['id']}", json={"is_default": True})
    delete_response = client.delete(f"/api/data-sources/{source['id']}")
    listed = client.get("/api/data-sources").json()["items"]

    assert updated.status_code == 200
    assert updated.json()["is_default"] is True
    assert sum(item["is_default"] for item in listed) == 1
    assert delete_response.status_code == 400
    assert "默认数据源" in delete_response.json()["detail"]


def test_non_default_data_source_can_be_deleted_and_missing_source_returns_404(tmp_path):
    database_path = tmp_path / "delete-source.db"
    app = create_app(database_path=database_path, llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "temporary_source",
            "db_type": "mysql",
            "database_url": "mysql://user:secret@localhost:3306/datapilot",
            "allowed_tables": ["orders"],
            "allowed_columns": {"orders": ["id", "amount", "product_name", "status"]},
        },
    ).json()

    deleted = client.delete(f"/api/data-sources/{source['id']}")
    deleted_again = client.delete(f"/api/data-sources/{source['id']}")
    missing_update = client.put("/api/data-sources/999999", json={"is_default": True})

    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert deleted_again.status_code == 404
    assert missing_update.status_code == 404


def test_chat_uses_data_source_table_whitelist(tmp_path):
    llm = UsersTableLLMClient()
    database_path = tmp_path / "table-whitelist.db"
    app = create_app(database_path=database_path, llm=llm, knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "orders_only",
            "db_type": "mysql",
            "database_url": "mysql://user:secret@localhost:3306/datapilot",
            "allowed_tables": ["orders"],
            "allowed_columns": {"orders": ["id", "amount", "product_name", "status"]},
        },
    ).json()

    response = client.post(
        "/api/chat",
        json={"question": "查一下用户列表", "data_source_id": source["id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_source_id"] == source["id"]
    assert payload["data"] == []
    assert "users" in payload["error"]
    assert "表：users" not in llm.prompts[0]
    assert "users.id" not in llm.prompts[0]
    assert "products.id" not in llm.prompts[0]
    assert "products.cost_price" not in llm.prompts[0]


def test_security_policies_can_use_data_source_whitelist(tmp_path):
    database_path = tmp_path / "policy-source.db"
    app = create_app(database_path=database_path, llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "orders_only",
            "db_type": "mysql",
            "database_url": "mysql://user:secret@localhost:3306/datapilot",
            "allowed_tables": ["orders"],
            "allowed_columns": {"orders": ["id", "amount", "product_name", "status"]},
        },
    ).json()

    response = client.get(f"/api/security/policies?data_source_id={source['id']}")

    assert response.status_code == 200
    assert response.json()["allowed_tables"] == ["orders"]


def test_chat_reuses_session_and_injects_recent_context(tmp_path):
    llm = FakeLLMClient()
    app = create_app(database_path=tmp_path / "session.db", llm=llm, knowledge=None)
    client = TestClient(app)

    first = client.post("/api/chat", json={"question": "请按商品统计销售额排名"}).json()
    second = client.post(
        "/api/chat",
        json={"question": "那按城市拆开看呢？", "session_id": first["session_id"]},
    ).json()

    assert second["session_id"] == first["session_id"]
    assert len(llm.prompts) == 2
    assert "最近会话上下文" in llm.prompts[1]
    assert "请按商品统计销售额排名" in llm.prompts[1]


def test_query_stats_returns_operational_metrics(tmp_path):
    app = create_app(database_path=tmp_path / "stats.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    client.post("/api/chat", json={"question": "请按商品统计销售额排名"})
    client.post("/api/chat", json={"question": "请删除所有订单数据"})

    response = client.get("/api/query-stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_queries"] == 2
    assert payload["success_queries"] == 1
    assert payload["failed_queries"] == 1
    assert payload["average_duration_ms"] >= 0
    assert payload["chart_type_counts"]["bar"] == 1
    assert payload["top_questions"]
    assert payload["error_code_counts"]["sql_safety_error"] == 1


def test_metrics_can_be_created_listed_updated_and_deleted(tmp_path):
    app = create_app(database_path=tmp_path / "metrics.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)

    list_response = client.get("/api/metrics")
    assert list_response.status_code == 200
    assert "销售额" in {item["name"] for item in list_response.json()["items"]}

    create_response = client.post(
        "/api/metrics",
        json={
            "metric_key": "repeat_order_count",
            "name": "复购订单数",
            "expression": "COUNT(orders.id)",
            "description": "重复购买订单数量。",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()

    update_response = client.put(
        f"/api/metrics/{created['id']}",
        json={"enabled": False},
    )
    assert update_response.status_code == 200
    assert update_response.json()["enabled"] is False

    delete_response = client.delete(f"/api/metrics/{created['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["ok"] is True


def test_chat_injects_configured_metrics_into_prompt(tmp_path):
    llm = FakeLLMClient()
    app = create_app(database_path=tmp_path / "metric-prompt.db", llm=llm, knowledge=None)
    client = TestClient(app)

    client.post(
        "/api/metrics",
        json={
            "metric_key": "repeat_order_count",
            "name": "复购订单数",
            "expression": "COUNT(orders.id)",
            "description": "重复购买订单数量。",
        },
    )
    response = client.post("/api/chat", json={"question": "请按商品统计销售额排名"})

    assert response.status_code == 200
    assert "复购订单数" in llm.prompts[0]


def test_catalog_endpoints_return_table_and_column_permissions(tmp_path):
    database_path = tmp_path / "catalog.db"
    app = create_app(database_path=database_path, llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "products_public",
            "db_type": "mysql",
            "database_url": "mysql://user:secret@localhost:3306/datapilot",
            "allowed_tables": ["products"],
            "allowed_columns": {"products": ["id", "product_name", "brand"]},
        },
    ).json()

    tables = client.get(f"/api/catalog/tables?data_source_id={source['id']}").json()["items"]
    columns = client.get(
        f"/api/catalog/tables/products/columns?data_source_id={source['id']}"
    ).json()["columns"]

    assert tables == [{"name": "products", "description": "商品维度表", "queryable": True}]
    assert next(column for column in columns if column["name"] == "brand")["queryable"] is True
    assert next(column for column in columns if column["name"] == "cost_price")["queryable"] is False


def test_chat_blocks_non_whitelisted_columns_and_hides_them_from_prompt(tmp_path):
    llm = ProductCostLLMClient()
    database_path = tmp_path / "column-whitelist.db"
    app = create_app(database_path=database_path, llm=llm, knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "products_public",
            "db_type": "mysql",
            "database_url": "mysql://user:secret@localhost:3306/datapilot",
            "allowed_tables": ["products"],
            "allowed_columns": {"products": ["id", "product_name", "brand"]},
        },
    ).json()

    response = client.post(
        "/api/chat",
        json={"question": "查一下商品成本价", "data_source_id": source["id"]},
    )
    logs = client.get("/api/query-logs").json()["items"]

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == []
    assert payload["error_code"] == "sql_safety_error"
    assert "cost_price" in payload["error"]
    assert "cost_price" not in llm.prompts[0]
    assert logs[0]["error_code"] == "sql_safety_error"


def test_postgresql_catalog_uses_postgres_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.database.PostgresClient", FakePostgresClient, raising=False)
    app = create_app(database_path=tmp_path / "pg-catalog.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "local_pg",
            "db_type": "postgresql",
            "database_url": "postgresql://datapilot:datapilot123@localhost:5432/datapilot",
            "allowed_tables": ["orders", "products"],
            "allowed_columns": {
                "orders": ["id", "product_name", "amount", "status"],
                "products": ["id", "product_name"],
            },
        },
    ).json()

    tables = client.get(f"/api/catalog/tables?data_source_id={source['id']}").json()["items"]
    columns = client.get(
        f"/api/catalog/tables/products/columns?data_source_id={source['id']}"
    ).json()["columns"]
    hidden_table = client.get(
        f"/api/catalog/tables/users/columns?data_source_id={source['id']}"
    )

    assert {table["name"] for table in tables} == {"orders", "products"}
    assert next(column for column in columns if column["name"] == "product_name")["queryable"] is True
    assert next(column for column in columns if column["name"] == "cost_price")["queryable"] is False
    assert hidden_table.status_code == 404


def test_mysql_catalog_uses_mysql_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.database.MySQLClient", FakeMySQLClient, raising=False)
    app = create_app(database_path=tmp_path / "mysql-catalog.db", llm=FakeLLMClient(), knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "local_mysql",
            "db_type": "mysql",
            "database_url": "mysql://datapilot_ro:datapilot123@localhost:3306/datapilot",
            "allowed_tables": ["orders", "products"],
            "allowed_columns": {
                "orders": ["id", "product_name", "amount", "status"],
                "products": ["id", "product_name"],
            },
        },
    ).json()

    tables = client.get(f"/api/catalog/tables?data_source_id={source['id']}").json()["items"]
    columns = client.get(
        f"/api/catalog/tables/products/columns?data_source_id={source['id']}"
    ).json()["columns"]

    assert {table["name"] for table in tables} == {"orders", "products"}
    assert next(column for column in columns if column["name"] == "product_name")["queryable"] is True
    assert next(column for column in columns if column["name"] == "cost_price")["queryable"] is False


def test_chat_executes_postgresql_data_source(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.database.PostgresClient", FakePostgresClient, raising=False)
    llm = PostgresLLMClient()
    app = create_app(database_path=tmp_path / "pg-chat.db", llm=llm, knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "local_pg",
            "db_type": "postgresql",
            "database_url": "postgresql://datapilot:datapilot123@localhost:5432/datapilot",
            "allowed_tables": ["orders"],
            "allowed_columns": {
                "orders": ["id", "product_name", "amount", "status"],
            },
        },
    ).json()

    response = client.post(
        "/api/chat",
        json={"question": "请按商品统计 MySQL 销售额", "data_source_id": source["id"]},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["data"] == [{"product_name": "无线鼠标", "total_amount": 128.5}]
    assert payload["answer"] == "PostgreSQL 查询返回 1 行。"
    assert payload["error"] is None
    assert "SQL 方言：postgresql" in llm.prompts[0]


def test_chat_executes_mysql_data_source_with_mysql_dialect(tmp_path, monkeypatch):
    from app.services.sql_validator import validate_select_sql as real_validate_select_sql

    monkeypatch.setattr("app.db.database.MySQLClient", FakeMySQLClient, raising=False)
    captured = {}

    def capture_dialect(sql, allowed_tables=None, allowed_columns=None, dialect="mysql"):
        captured["dialect"] = dialect
        return real_validate_select_sql(sql, allowed_tables, allowed_columns, dialect)

    monkeypatch.setattr("app.agent.workflow.validate_select_sql", capture_dialect)
    llm = MySQLLLMClient()
    app = create_app(database_path=tmp_path / "mysql-chat.db", llm=llm, knowledge=None)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "local_mysql",
            "db_type": "mysql",
            "database_url": "mysql://datapilot_ro:datapilot123@localhost:3306/datapilot",
            "allowed_tables": ["orders"],
            "allowed_columns": {
                "orders": ["id", "product_name", "amount", "status"],
            },
        },
    ).json()

    response = client.post(
        "/api/chat",
        json={"question": "请按商品统计 MySQL 销售额", "data_source_id": source["id"]},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["data"] == [{"product_name": "无线鼠标", "total_amount": 128.5}]
    assert payload["answer"] == "MySQL 查询返回 1 行。"
    assert payload["trusted_answer"] is False
    assert payload["error"] is None
    assert captured["dialect"] == "mysql"
    assert "SQL 方言：mysql" in llm.prompts[0]
