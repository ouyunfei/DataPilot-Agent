import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_docker_assets_exist_and_use_env_file():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "uvicorn" in dockerfile
    assert "8000" in dockerfile
    assert "env_file" in compose
    assert ".env" in compose
    assert ".env" in dockerignore


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
