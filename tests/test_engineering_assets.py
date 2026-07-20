import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_docker_assets_exist_and_use_env_file():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    postgres_init = ROOT / "docker" / "postgres" / "init.sql"
    mysql_init = ROOT / "docker" / "mysql" / "init.sql"

    assert "uvicorn" in dockerfile
    assert "8000" in dockerfile
    assert "env_file" in compose
    assert ".env" in compose
    assert "postgres:" in compose
    assert "mysql:" in compose
    assert "qdrant:" not in compose
    assert "mysql_data:" in compose
    assert "${MYSQL_PORT:-3307}:3306" in compose
    assert postgres_init.exists()
    assert mysql_init.exists()
    postgres_sql = postgres_init.read_text(encoding="utf-8")
    assert "CREATE TABLE orders" in postgres_sql
    assert "generate_series(1, 1000)" in postgres_sql
    mysql_sql = mysql_init.read_text(encoding="utf-8")
    assert "SET NAMES utf8mb4" in mysql_sql
    assert "CREATE TABLE orders" in mysql_sql
    assert "CREATE USER" in mysql_sql
    assert "GRANT SELECT" in mysql_sql
    assert "PyMySQL[rsa]" in requirements
    assert "qdrant-client==1.18.0" in requirements
    assert "sentence-transformers==5.6.0" in requirements
    assert ".env" in dockerignore
    assert "data/qdrant/" in dockerignore
    assert "data/qdrant/" in gitignore
    assert "QDRANT_PATH=data/qdrant" in env_example
    assert "QDRANT_COLLECTION=datapilot_knowledge_bge_small_zh_v15" in env_example
    assert "EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5" in env_example
    assert "KNOWLEDGE_TOP_K=5" in env_example
    assert "META_DB_TYPE=mysql" in env_example
    assert "META_DATABASE_URL=mysql://user:password@localhost:3306/datapilot" in env_example


def test_config_defaults_to_mysql_in_clean_environment(tmp_path):
    script = """
import json
from app.core.config import META_DATABASE_URL, META_DB_TYPE
print(json.dumps({
    "meta_db_type": META_DB_TYPE,
    "meta_database_url": META_DATABASE_URL,
}))
"""
    env = {key: value for key, value in os.environ.items() if key not in {"META_DB_TYPE", "META_DATABASE_URL"}}
    env["PYTHONPATH"] = str(ROOT)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["meta_db_type"] == "mysql"
    assert payload["meta_database_url"] == "mysql://root:0522@127.0.0.1:3306/datapilot"


def test_ci_runs_pytest_without_deepseek_secret():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "python -m pytest -q" in ci
    assert "requirements.txt" in ci
    assert "DEEPSEEK_API_KEY" not in ci


def test_eval_questions_have_expected_shape():
    questions = json.loads((ROOT / "evals" / "questions.json").read_text(encoding="utf-8"))

    assert len(questions) >= 7
    for item in questions:
        assert {"id", "question", "expected_fields", "expected_chart_type", "should_be_safe", "description"} <= item.keys()


def test_eval_script_runs_successfully():
    result = subprocess.run(
        [sys.executable, "scripts/run_evals.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Eval passed:" in result.stdout
    assert "Success rate:" in result.stdout
    assert "Synthetic RAG workflow check: off 0/3, on 3/3" in result.stdout
    assert "Synthetic workflow delta: +100.00pp" in result.stdout
    assert "Uses a fake LLM/retriever; not a real-model quality benchmark." in result.stdout
    assert "RAG improvement" not in result.stdout


def test_synthetic_rag_failure_diagnostic_names_case_and_arm(monkeypatch):
    from scripts import run_evals

    item = {
        "id": "gross_profit_by_brand",
        "question": "question",
        "expected_sql_fragments": ["orders.amount - products.cost_price"],
    }

    class SemanticallyWrongAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, _question):
            return {"sql": "SELECT SUM(orders.amount) FROM orders", "data": [{"value": 1}]}

    monkeypatch.setattr(run_evals, "RAG_CASES", [item])
    monkeypatch.setattr(run_evals, "DataAnalysisAgent", SemanticallyWrongAgent)

    assert run_evals._run_rag_comparison(object()) == (
        0,
        0,
        True,
        ["gross_profit_by_brand [on]: semantic SQL expectations failed"],
    )
