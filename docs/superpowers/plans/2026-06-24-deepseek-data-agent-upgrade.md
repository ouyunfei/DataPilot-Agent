# DeepSeek Data Agent Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade DataPilot Agent to use DeepSeek by default, expand the SQLite sample schema to `orders/users/products`, add SQL explanations, improve Top 5 answers, and harden SQL safety with SQLGlot.

**Architecture:** Keep the existing FastAPI + LangGraph shape. Replace the runtime LLM path with `DeepSeekLLMClient`, keep tests deterministic through injected fake clients, expand `SQLiteDatabase`, and make `sql_validator` responsible for AST-based enforcement and LIMIT normalization.

**Tech Stack:** Python, FastAPI, LangGraph, Pydantic, SQLite, DeepSeek OpenAI-compatible API via `httpx`, SQLGlot, pytest.

---

## File Map

- Modify `requirements.txt`: add `sqlglot` and `python-dotenv`.
- Modify `.gitignore`: ignore `.env`.
- Modify `app/core/config.py`: add environment loading and DeepSeek settings.
- Modify `app/services/llm.py`: add structured SQL generation result, DeepSeek client, JSON extraction, and prompt builders.
- Modify `app/db/database.py`: create and seed `users`, `products`, and upgraded `orders`.
- Modify `app/services/sql_validator.py`: replace simple validation with SQLGlot AST checks and LIMIT enforcement.
- Modify `app/agent/workflow.py`: add `sql_explanation` to state and flow.
- Modify `app/schemas/chat.py`: add `sql_explanation` response field.
- Modify `app/api/routes.py`: return `sql_explanation`.
- Modify `app/main.py`: instantiate DeepSeek by default; support test injection.
- Modify `tests/test_sql_validator.py`: update safety expectations.
- Modify `tests/test_database.py`: assert three-table schema and joins.
- Modify `tests/test_api.py`: use fake LLM injection and assert `sql_explanation`.
- Modify `README.md` and `docs/mvp-design.md`: document upgrade.

## Tasks

### Task 1: Write Failing Tests

- [ ] Update tests for the new API field, three-table schema, and SQL safety behavior.
- [ ] Run `python -m pytest -q` and verify failures are due to missing implementation.

### Task 2: Dependencies and Config

- [ ] Add `sqlglot` and `python-dotenv`.
- [ ] Ignore `.env`.
- [ ] Add settings for `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, and `DEEPSEEK_BASE_URL`.

### Task 3: Database Upgrade

- [ ] Create `users`, `products`, and upgraded `orders`.
- [ ] Reset incompatible old sample schema automatically.
- [ ] Seed deterministic sample data.
- [ ] Return schema descriptions for all three tables.

### Task 4: SQLGlot Validator

- [ ] Parse SQLite SQL with SQLGlot.
- [ ] Allow only one `SELECT`.
- [ ] Reject comments, multi-statements, dangerous keywords, `SELECT *`, and non-whitelisted tables.
- [ ] Add or cap `LIMIT` at 100.

### Task 5: DeepSeek LLM Client

- [ ] Add structured `SQLGeneration` result.
- [ ] Implement DeepSeek SQL generation and analysis methods.
- [ ] Extract JSON safely from model responses.
- [ ] Raise clear errors on missing API key or invalid model output.

### Task 6: Workflow and API

- [ ] Thread `sql_explanation` through LangGraph state.
- [ ] Return it from `POST /api/chat`.
- [ ] Allow test injection of fake LLM clients.

### Task 7: Docs and Verification

- [ ] Update README and MVP design doc.
- [ ] Run full tests.
- [ ] Run a local app health check.
- [ ] Optionally verify a real DeepSeek request if environment key is configured.
