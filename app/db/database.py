from __future__ import annotations

import json
import re
from typing import Any

from app.db.mysql import MySQLClient
from app.db.postgres import PostgresClient


ORDER_FIELD_DESCRIPTIONS = {
    "id": "订单 ID，主键",
    "user_id": "用户 ID",
    "product_id": "商品 ID，关联 products.id",
    "product_name": "商品名称",
    "category": "商品品类",
    "city": "下单城市",
    "amount": "订单金额，单位：元",
    "status": "订单状态，paid 表示已支付，refunded 表示已退款，cancelled 表示已取消",
    "created_at": "下单日期，ISO 日期格式",
    "refund_amount": "退款金额，未退款为 0",
}

USER_FIELD_DESCRIPTIONS = {
    "id": "用户 ID，主键",
    "name": "用户姓名",
    "city": "用户常驻城市",
    "level": "用户等级，包含 普通、银卡、金卡、黑金",
    "registered_at": "用户注册日期",
}

PRODUCT_FIELD_DESCRIPTIONS = {
    "id": "商品 ID，主键",
    "product_name": "商品名称",
    "category": "商品品类",
    "brand": "商品品牌",
    "cost_price": "成本价，单位：元",
    "list_price": "标价，单位：元",
}

TABLE_DESCRIPTIONS = {
    "orders": ("订单事实表", ORDER_FIELD_DESCRIPTIONS),
    "users": ("用户维度表", USER_FIELD_DESCRIPTIONS),
    "products": ("商品维度表", PRODUCT_FIELD_DESCRIPTIONS),
}

DEFAULT_METRICS = [
    {
        "metric_key": "sales_amount",
        "name": "销售额",
        "expression": "SUM(orders.amount)",
        "description": "已支付订单金额总和。",
    },
    {
        "metric_key": "refund_rate",
        "name": "退款率",
        "expression": "退款订单数 / 总订单数",
        "description": "refund_amount > 0 或 status = 'refunded' 的订单占比。",
    },
    {
        "metric_key": "average_order_value",
        "name": "客单价",
        "expression": "SUM(orders.amount) / COUNT(DISTINCT orders.id)",
        "description": "平均每笔订单金额。",
    },
    {
        "metric_key": "gross_profit",
        "name": "毛利",
        "expression": "SUM(orders.amount - products.cost_price)",
        "description": "订单金额减商品成本价后的金额。",
    },
    {
        "metric_key": "order_count",
        "name": "订单数",
        "expression": "COUNT(orders.id)",
        "description": "订单明细数量。",
    },
]

FORBIDDEN_METRIC_EXPRESSION_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "REPLACE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "VACUUM",
    "REINDEX",
}

SUPPORTED_DATA_SOURCE_TYPES = {"mysql", "postgresql"}


class DataPilotDatabase:
    """Common data-source behavior; platform metadata is implemented by subclasses."""

    def initialize(self) -> None:
        raise NotImplementedError

    def list_metrics(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        raise NotImplementedError

    def list_data_sources(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_data_source(self, source_id: int) -> dict[str, Any] | None:
        raise NotImplementedError

    def get_default_data_source(self) -> dict[str, Any]:
        raise NotImplementedError

    def list_high_quality_historical_qa(self, data_source_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_data_source_schema_description(self, source: dict[str, Any]) -> str:
        if source["db_type"] == "mysql":
            return self._get_schema_description(source, "mysql", MySQLClient(source["database_url"]))
        if source["db_type"] == "postgresql":
            return self._get_schema_description(source, "postgresql", PostgresClient(source["database_url"]))
        return f"SQL 方言：{source['db_type']}。\n当前阶段不支持该数据源执行查询。"

    def list_tables(self) -> list[str]:
        return [table["name"] for table in self.list_catalog_tables()]

    def execute_data_source_select(
        self,
        source: dict[str, Any],
        sql: str,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        if source["db_type"] == "mysql":
            return MySQLClient(source["database_url"]).execute_select(sql, timeout_seconds)
        if source["db_type"] == "postgresql":
            return PostgresClient(source["database_url"]).execute_select(sql, timeout_seconds)
        raise ValueError("当前阶段仅支持 MySQL 和 PostgreSQL 数据源执行查询")

    def test_data_source(self, source_id: int) -> dict[str, Any]:
        source = self.get_data_source(source_id)
        if source is None:
            return {"ok": False, "message": "数据源不存在"}
        if source["db_type"] == "mysql":
            return MySQLClient(source["database_url"]).test_connection(
                source["allowed_tables"],
                source["allowed_columns"],
            )
        if source["db_type"] == "postgresql":
            return PostgresClient(source["database_url"]).test_connection(
                source["allowed_tables"],
                source["allowed_columns"],
            )
        return {"ok": False, "message": "当前阶段仅支持 MySQL 和 PostgreSQL 数据源"}

    def list_catalog_tables(
        self,
        data_source_id: int | None = None,
        include_non_queryable: bool = False,
    ) -> list[dict[str, Any]]:
        source = self._source(data_source_id)
        client = self._client_for_source(source)
        allowed_tables = set(source["allowed_tables"])
        existing_tables = set(client.list_tables())
        selected_tables = existing_tables if include_non_queryable else existing_tables & allowed_tables
        return [
            {
                "name": table,
                "description": TABLE_DESCRIPTIONS.get(table, ("", {}))[0],
                "queryable": table in allowed_tables,
            }
            for table in sorted(selected_tables)
        ]

    def list_catalog_columns(
        self,
        table_name: str,
        data_source_id: int | None = None,
        include_non_queryable: bool = False,
    ) -> list[dict[str, Any]]:
        table_name = table_name.lower()
        source = self._source(data_source_id)
        table_queryable = table_name in source["allowed_tables"]
        if not table_queryable and not include_non_queryable:
            return []

        allowed = set(source["allowed_columns"].get(table_name, [])) if table_queryable else set()
        _, field_descriptions = TABLE_DESCRIPTIONS.get(table_name, ("", {}))
        return [
            {
                "name": row["name"],
                "type": row["type"],
                "description": field_descriptions.get(row["name"], ""),
                "queryable": row["name"] in allowed,
            }
            for row in self._client_for_source(source).list_columns(table_name)
        ]

    def _source(self, data_source_id: int | None) -> dict[str, Any]:
        source = self.get_data_source(data_source_id) if data_source_id is not None else self.get_default_data_source()
        if source is None:
            raise ValueError("数据源不存在")
        return source

    def _client_for_source(self, source: dict[str, Any]) -> MySQLClient | PostgresClient:
        if source["db_type"] == "mysql":
            return MySQLClient(source["database_url"])
        if source["db_type"] == "postgresql":
            return PostgresClient(source["database_url"])
        raise ValueError("当前阶段仅支持 MySQL 和 PostgreSQL 数据源")

    def _get_schema_description(
        self,
        source: dict[str, Any],
        dialect: str,
        _client: MySQLClient | PostgresClient,
    ) -> str:
        selected_tables = set(source["allowed_tables"])
        lines = [f"SQL 方言：{dialect}。"]
        lines.append(f"当前允许查询的业务表：{'、'.join(sorted(selected_tables))}。")
        if {"orders", "users"} <= selected_tables:
            lines.append("表关系：orders.user_id = users.id。")
        if {"orders", "products"} <= selected_tables:
            lines.append("表关系：orders.product_id = products.id。")

        for table in source["allowed_tables"]:
            columns = self.list_catalog_columns(table, source["id"])
            if not columns:
                continue
            table_comment = TABLE_DESCRIPTIONS.get(table, ("", {}))[0]
            lines.append("")
            lines.append(f"表：{table}（{table_comment}）")
            lines.append("字段：")
            for column in columns:
                if column["queryable"]:
                    lines.append(f"- {column['name']} ({column['type']})：{column['description']}")
        return "\n".join(lines)

    @staticmethod
    def _validate_metric(metric_key: str, name: str, expression: str, description: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", metric_key):
            raise ValueError("metric_key 必须为小写字母、数字或下划线，且以字母开头")
        if not name:
            raise ValueError("name 不能为空")
        if not expression:
            raise ValueError("expression 不能为空")
        if not description:
            raise ValueError("description 不能为空")
        if ";" in expression or "--" in expression or "/*" in expression or "*/" in expression:
            raise ValueError("expression 不允许包含注释或分号")
        upper_expression = expression.upper()
        for keyword in FORBIDDEN_METRIC_EXPRESSION_KEYWORDS:
            if re.search(rf"\b{keyword}\b", upper_expression):
                raise ValueError(f"expression 不允许包含 {keyword}")

    @staticmethod
    def _metric_from_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "metric_key": row["metric_key"],
            "name": row["name"],
            "expression": row["expression"],
            "description": row["description"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _data_source_from_row(row: dict[str, Any]) -> dict[str, Any]:
        allowed_tables = json.loads(row["allowed_tables"])
        allowed_columns_raw = row.get("allowed_columns")
        allowed_columns = (
            json.loads(allowed_columns_raw)
            if allowed_columns_raw
            else DataPilotDatabase._default_allowed_columns(allowed_tables)
        )
        return {
            "id": row["id"],
            "name": row["name"],
            "db_type": row["db_type"],
            "database_url": row["database_url"],
            "allowed_tables": allowed_tables,
            "allowed_columns": allowed_columns,
            "is_default": bool(row["is_default"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _default_allowed_columns(allowed_tables: list[str]) -> dict[str, list[str]]:
        return {
            table: list(TABLE_DESCRIPTIONS[table][1].keys())
            for table in allowed_tables
            if table in TABLE_DESCRIPTIONS
        }

    @staticmethod
    def _normalize_allowed_columns(
        allowed_tables: list[str],
        allowed_columns: dict[str, list[str]] | None,
    ) -> dict[str, list[str]]:
        defaults = DataPilotDatabase._default_allowed_columns(allowed_tables)
        if not allowed_columns:
            return defaults

        normalized: dict[str, list[str]] = {}
        for table in allowed_tables:
            requested = [
                column.strip().lower()
                for column in allowed_columns.get(table, [])
                if column.strip()
            ]
            normalized[table] = requested or defaults.get(table, [])
        return normalized
