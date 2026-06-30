# Repository Guidelines

## Project Structure & Module Organization

This is a Python FastAPI backend for a LangGraph-based data analysis Agent.

- `app/main.py`: FastAPI app factory and `/health`.
- `app/api/`: HTTP routes, including `/api/chat`, query logs, and security policies.
- `app/agent/`: LangGraph workflow nodes and state.
- `app/db/`: SQLite setup, seed data, schema descriptions, and query execution.
- `app/services/`: LLM client, SQL safety validation, semantic layer, trusted answers, and chart recommendation.
- `app/schemas/`: Pydantic request/response models.
- `tests/`: pytest unit and API tests.
- `evals/` and `scripts/run_evals.py`: deterministic Text-to-SQL eval suite.
- `docs/`: design notes and feature specs.

## Build, Test, and Development Commands

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
python -m pytest -q
python scripts/run_evals.py
docker compose up --build
```

- `uvicorn` runs the local API at `http://127.0.0.1:8000`.
- `pytest` verifies API, database, SQL safety, semantic logic, and engineering assets.
- `run_evals.py` checks the Agent workflow with fake LLM SQL.
- Docker starts the backend container on port `8000`.

## Coding Style & Naming Conventions

Use Python 3.11+, 4-space indentation, type hints for public functions, and small focused modules. Keep business logic out of `main.py`; add it to `app/services/`, `app/db/`, or `app/agent/` as appropriate. Use `snake_case` for functions, variables, and files; use `PascalCase` for Pydantic models and classes.

## Testing Guidelines

Use `pytest`. Name tests `test_*.py` and prefer behavior-focused names, for example `test_chat_returns_error_when_generated_sql_is_unsafe`. Tests must not call real DeepSeek; inject fake LLM clients instead. Run both:

```bash
python -m pytest -q
python scripts/run_evals.py
```

## Commit & Pull Request Guidelines

Current commits use concise Conventional Commit style, such as `feat: add agent engineering workflow`. Keep messages clear: what changed and why. PRs should include a short summary, test results, API changes if any, and screenshots only when UI is involved.

## Security & Configuration Tips

Never commit `.env`, real DeepSeek API keys, SQLite databases in `data/*.db`, or `.claude/`. Keep `.env.example` as placeholders only. All generated SQL must pass `app/services/sql_validator.py` before execution.
