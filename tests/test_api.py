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


def test_chat_returns_sql_data_and_chinese_answer(tmp_path):
    app = create_app(database_path=tmp_path / "chat.db", llm=FakeLLMClient())
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


def test_chat_returns_error_when_generated_sql_is_unsafe(tmp_path):
    app = create_app(database_path=tmp_path / "unsafe.db", llm=FakeLLMClient())
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
    app = create_app(database_path=tmp_path / "llm-error.db", llm=FailingLLMClient())
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": "请分析商品销售额排名"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == []
    assert payload["answer"] == ""
    assert "LLM 调用失败" in payload["error"]


def test_chat_uses_trusted_answer_and_writes_query_log(tmp_path):
    database_path = tmp_path / "trusted.db"
    app = create_app(database_path=database_path, llm=AnalyzeOnlyLLMClient())
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

    from app.db.database import SQLiteDatabase

    db = SQLiteDatabase(database_path)
    rows = db.execute_select(
        """
        SELECT question, trusted_answer, chart_type, row_count, error
        FROM query_logs
        ORDER BY id DESC
        LIMIT 1
        """
    )
    assert rows[0]["question"] == "最近 30 天销售额最高的 5 个商品是什么？"
    assert rows[0]["trusted_answer"] == 1
    assert rows[0]["chart_type"] == "bar"
    assert rows[0]["row_count"] == len(payload["data"])
    assert rows[0]["error"] is None


def test_query_logs_can_be_listed_and_feedback_can_be_saved(tmp_path):
    database_path = tmp_path / "logs.db"
    app = create_app(database_path=database_path, llm=AnalyzeOnlyLLMClient())
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
    app = create_app(database_path=tmp_path / "missing-log.db", llm=FakeLLMClient())
    client = TestClient(app)

    response = client.post(
        "/api/query-logs/999/feedback",
        json={"feedback": "dislike", "note": "不存在"},
    )

    assert response.status_code == 404


def test_health_returns_database_and_deepseek_status_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DEEPSEEK_API_KEY", "sk-secret-value")
    app = create_app(database_path=tmp_path / "health.db", llm=FakeLLMClient())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database_status"] == "ok"
    assert payload["deepseek_configured"] is True
    assert payload["table_count"] >= 4
    assert "sk-secret-value" not in response.text


def test_health_treats_placeholder_deepseek_key_as_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DEEPSEEK_API_KEY", "your_deepseek_api_key")
    app = create_app(database_path=tmp_path / "placeholder-health.db", llm=FakeLLMClient())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["deepseek_configured"] is False


def test_app_can_start_without_deepseek_key(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DEEPSEEK_API_KEY", "")
    app = create_app(database_path=tmp_path / "no-key.db")
    client = TestClient(app)

    health = client.get("/health")
    chat = client.post("/api/chat", json={"question": "请分析商品销售额排名"})

    assert health.status_code == 200
    assert health.json()["deepseek_configured"] is False
    assert chat.status_code == 200
    assert "DEEPSEEK_API_KEY" in chat.json()["error"]


def test_security_policies_endpoint_returns_current_sql_rules(tmp_path):
    app = create_app(database_path=tmp_path / "security.db", llm=FakeLLMClient())
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
    app = create_app(database_path=database_path, llm=FakeLLMClient())
    client = TestClient(app)

    default_sources = client.get("/api/data-sources").json()["items"]
    create_response = client.post(
        "/api/data-sources",
        json={
            "name": "orders_only",
            "db_type": "sqlite",
            "database_url": str(database_path),
            "allowed_tables": ["orders"],
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["name"] == "orders_only"
    assert created["allowed_tables"] == ["orders"]
    assert any(source["name"] == "default_sqlite" for source in default_sources)

    listed = client.get("/api/data-sources").json()["items"]
    assert any(source["name"] == "orders_only" for source in listed)

    test_response = client.post(f"/api/data-sources/{created['id']}/test")
    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True


def test_postgresql_data_source_config_does_not_require_external_connection(tmp_path):
    app = create_app(database_path=tmp_path / "postgres-config.db", llm=FakeLLMClient())
    client = TestClient(app)

    created = client.post(
        "/api/data-sources",
        json={
            "name": "warehouse_pg",
            "db_type": "postgresql",
            "database_url": "postgresql://user:password@localhost:5432/warehouse",
            "allowed_tables": ["orders"],
        },
    ).json()

    test_response = client.post(f"/api/data-sources/{created['id']}/test")

    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True
    assert "真实连接待后续接入驱动" in test_response.json()["message"]


def test_chat_uses_data_source_table_whitelist(tmp_path):
    llm = UsersTableLLMClient()
    database_path = tmp_path / "table-whitelist.db"
    app = create_app(database_path=database_path, llm=llm)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "orders_only",
            "db_type": "sqlite",
            "database_url": str(database_path),
            "allowed_tables": ["orders"],
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
    app = create_app(database_path=database_path, llm=FakeLLMClient())
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "orders_only",
            "db_type": "sqlite",
            "database_url": str(database_path),
            "allowed_tables": ["orders"],
        },
    ).json()

    response = client.get(f"/api/security/policies?data_source_id={source['id']}")

    assert response.status_code == 200
    assert response.json()["allowed_tables"] == ["orders"]


def test_chat_reuses_session_and_injects_recent_context(tmp_path):
    llm = FakeLLMClient()
    app = create_app(database_path=tmp_path / "session.db", llm=llm)
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
    app = create_app(database_path=tmp_path / "stats.db", llm=FakeLLMClient())
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
    app = create_app(database_path=tmp_path / "metrics.db", llm=FakeLLMClient())
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
    app = create_app(database_path=tmp_path / "metric-prompt.db", llm=llm)
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
    app = create_app(database_path=database_path, llm=FakeLLMClient())
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "products_public",
            "db_type": "sqlite",
            "database_url": str(database_path),
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
    app = create_app(database_path=database_path, llm=llm)
    client = TestClient(app)
    source = client.post(
        "/api/data-sources",
        json={
            "name": "products_public",
            "db_type": "sqlite",
            "database_url": str(database_path),
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
