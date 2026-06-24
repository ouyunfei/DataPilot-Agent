from fastapi.testclient import TestClient

from app.main import create_app
from app.services.llm import SQLGeneration


class FakeLLMClient:
    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
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


def test_chat_returns_sql_data_and_chinese_answer(tmp_path):
    app = create_app(database_path=tmp_path / "chat.db", llm=FakeLLMClient())
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": "最近 30 天销售额最高的 5 个商品是什么？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["question"] == "最近 30 天销售额最高的 5 个商品是什么？"
    assert payload["sql"].upper().startswith("SELECT")
    assert payload["sql_explanation"] == "按商品名称分组，统计已支付订单销售额，并按销售额倒序取前 5 名。"
    assert payload["data"]
    assert "Top 5" in payload["answer"]
    assert payload["error"] is None


def test_chat_returns_error_when_generated_sql_is_unsafe(tmp_path):
    app = create_app(database_path=tmp_path / "unsafe.db", llm=FakeLLMClient())
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": "请删除所有订单数据"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == []
    assert payload["answer"] == ""
    assert payload["sql_explanation"] == "尝试删除订单数据。"
    assert "只允许执行 SELECT 查询" in payload["error"]


def test_chat_returns_error_when_llm_fails(tmp_path):
    app = create_app(database_path=tmp_path / "llm-error.db", llm=FailingLLMClient())
    client = TestClient(app)

    response = client.post("/api/chat", json={"question": "最近 30 天销售额最高的 5 个商品是什么？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == []
    assert payload["answer"] == ""
    assert "LLM 调用失败" in payload["error"]
