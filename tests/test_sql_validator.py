import pytest

from app.services.sql_validator import SQLSafetyError, validate_select_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT product_name, SUM(amount) AS total_amount FROM orders GROUP BY product_name LIMIT 5",
        "SELECT id, product_name FROM orders WHERE product_name = 'DROP键盘' LIMIT 5",
    ],
)
def test_validate_select_sql_allows_safe_select_and_enforces_limit(sql):
    validated = validate_select_sql(sql)
    assert validated.upper().startswith("SELECT")
    assert "LIMIT" in validated.upper()


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "UPDATE orders SET amount = 1",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN note TEXT",
        "TRUNCATE TABLE orders",
        "INSERT INTO orders (id) VALUES (1)",
        "SELECT * FROM orders; DROP TABLE orders;",
        "SELECT * FROM orders LIMIT 5",
        "SELECT id FROM payments LIMIT 5",
    ],
)
def test_validate_select_sql_blocks_dangerous_sql(sql):
    with pytest.raises(SQLSafetyError):
        validate_select_sql(sql)


@pytest.mark.parametrize("sql", ["", "   ", "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent"])
def test_validate_select_sql_requires_direct_select(sql):
    with pytest.raises(SQLSafetyError):
        validate_select_sql(sql)


def test_validate_select_sql_adds_limit_when_missing():
    validated = validate_select_sql("SELECT id, product_name FROM orders ORDER BY id")

    assert validated.endswith("LIMIT 100")


def test_validate_select_sql_caps_large_limit():
    validated = validate_select_sql("SELECT id, product_name FROM orders LIMIT 1000")

    assert validated.endswith("LIMIT 100")
