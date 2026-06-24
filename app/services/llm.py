from __future__ import annotations

import json
import re
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field


class BaseLLMClient(Protocol):
    def generate_sql(self, question: str, schema: str) -> "SQLGeneration":
        """Generate SQL from a natural-language question and schema context."""

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict[str, Any]],
    ) -> str:
        """Generate a Chinese business analysis summary from query results."""


class LLMError(RuntimeError):
    """Raised when the configured LLM cannot produce a usable response."""


class SQLGeneration(BaseModel):
    sql: str = Field(..., min_length=1)
    sql_explanation: str = Field(..., min_length=1)


class DeepSeekLLMClient:
    """DeepSeek OpenAI-compatible chat client."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 30,
    ) -> None:
        if not api_key:
            raise LLMError("缺少 DEEPSEEK_API_KEY，请在 .env 或环境变量中配置。")

        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def generate_sql(self, question: str, schema: str) -> SQLGeneration:
        content = self._chat(
            [
                {"role": "system", "content": self._sql_system_prompt()},
                {"role": "user", "content": f"数据库 Schema：\n{schema}\n\n用户问题：{question}"},
            ]
        )
        payload = _extract_json_object(content)
        return SQLGeneration.model_validate(payload)

    def analyze_result(
        self,
        question: str,
        sql: str,
        sql_explanation: str,
        rows: list[dict[str, Any]],
    ) -> str:
        if not rows:
            return "未查询到符合条件的数据。"

        content = self._chat(
            [
                {"role": "system", "content": self._analysis_system_prompt()},
                {
                    "role": "user",
                    "content": (
                        f"用户问题：{question}\n\n"
                        f"SQL：\n{sql}\n\n"
                        f"SQL解释：{sql_explanation}\n\n"
                        f"查询结果 JSON：\n{json.dumps(rows[:20], ensure_ascii=False)}"
                    ),
                },
            ]
        )
        return content.strip()

    def _chat(self, messages: list[dict[str, str]]) -> str:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.1,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"DeepSeek 返回格式异常：{payload}") from exc

    @staticmethod
    def _sql_system_prompt() -> str:
        return (
            "你是资深数据分析 SQL Agent。请根据用户问题和数据库 Schema 生成 SQLite SQL。\n"
            "必须严格遵守：\n"
            "1. 只返回 JSON 对象，不要 Markdown，不要代码块。\n"
            "2. JSON 字段只能包含 sql 和 sql_explanation。\n"
            "3. SQL 只能是 SELECT 查询。\n"
            "4. 禁止 SELECT *。\n"
            "5. 只能使用 orders、users、products 三张表。\n"
            "6. 必须包含 LIMIT，默认不超过 100。\n"
            "7. 排行问题优先 LIMIT 5 或 LIMIT 10。\n"
            "8. 金额字段使用 ROUND(..., 2)。\n"
            "9. SQL 方言必须兼容 SQLite。\n"
            "示例输出："
            "{\"sql\":\"SELECT product_name, ROUND(SUM(amount), 2) AS total_amount FROM orders "
            "GROUP BY product_name ORDER BY total_amount DESC LIMIT 5\","
            "\"sql_explanation\":\"按商品名称分组统计销售额，并按销售额倒序取前 5 名。\"}"
        )

    @staticmethod
    def _analysis_system_prompt() -> str:
        return (
            "你是中文业务数据分析师。请基于用户问题、SQL、SQL解释和查询结果生成简洁分析结论。\n"
            "要求：\n"
            "1. 用中文回答。\n"
            "2. 排行类结果要总结 Top 5，不要只说第一名。\n"
            "3. 包含关键数值和简短业务洞察。\n"
            "4. 不要编造查询结果中不存在的数据。\n"
            "5. 控制在 200 字以内。\n"
            "6. 只输出纯文本，不要使用 Markdown 加粗、标题或列表符号。"
        )


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise LLMError(f"DeepSeek 未返回 JSON：{content}")
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise LLMError(f"DeepSeek JSON 不是对象：{content}")
    return parsed
