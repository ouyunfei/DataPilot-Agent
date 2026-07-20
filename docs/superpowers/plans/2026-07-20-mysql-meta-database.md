# MySQL Meta Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compatible MySQL metadata backend so DataPilot stores data sources, metrics, query logs, feedback and chat sessions in MySQL when `META_DB_TYPE=mysql`.

**Architecture:** Keep the existing `SQLiteDatabase` public API. Add one `MySQLMetaDatabase` subclass that overrides only platform metadata methods while reusing existing business data-source execution and catalog behavior. Choose the metadata backend in `app/main.py` from two environment variables, and provide one SQLite-to-MySQL migration script.

**Tech Stack:** Python 3.11, FastAPI, PyMySQL, SQLite, pytest.

---

## File Map

### Create

- `app/db/meta_mysql.py`: MySQL platform metadata backend.
- `scripts/migrate_sqlite_meta_to_mysql.py`: one-shot metadata migration script.
- `tests/test_meta_mysql.py`: deterministic fake-connection tests for MySQL metadata behavior.
- `docs/superpowers/plans/2026-07-20-mysql-meta-database.md`: this implementation plan.

### Modify

- `app/core/config.py`: add `META_DB_TYPE` and `META_DATABASE_URL`.
- `.env.example`: document MySQL metadata settings.
- `app/main.py`: select SQLite or MySQL metadata backend.
- `tests/test_api.py`: cover backend selection through `create_app()`.
- `tests/test_engineering_assets.py`: assert config/docs assets.
- `README.md`, `docs/mvp-design.md`, `docs/storage-architecture-roadmap.md`: document compatible switch and migration.

---

### Task 1: Configuration and Backend Selection

**Files:**
- Modify: `app/core/config.py`
- Modify: `.env.example`
- Modify: `app/main.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_engineering_assets.py`

- [x] **Step 1: Write failing config/backend tests**

Add tests that assert `.env.example` contains `META_DB_TYPE=sqlite` and `META_DATABASE_URL=`, and that `create_app()` constructs `MySQLMetaDatabase` when `app.main.META_DB_TYPE == "mysql"`.

- [x] **Step 2: Verify tests fail**

Run:

```bash
python -m pytest tests/test_engineering_assets.py::test_docker_assets_exist_and_use_env_file tests/test_api.py::test_create_app_uses_mysql_meta_database_when_configured -q
```

Expected: FAIL because the config and class do not exist.

- [x] **Step 3: Implement minimal config and backend selection**

Add config constants, a `_create_database()` helper in `app/main.py`, and select `MySQLMetaDatabase` only for `META_DB_TYPE=mysql`. Keep SQLite as default.

- [x] **Step 4: Verify focused tests pass**

Run the same focused pytest command. Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/core/config.py .env.example app/main.py tests/test_api.py tests/test_engineering_assets.py
git commit -m "feat: select mysql meta database by config"
```

---

### Task 2: MySQL Metadata Backend

**Files:**
- Create: `app/db/meta_mysql.py`
- Create/Modify: `tests/test_meta_mysql.py`

- [x] **Step 1: Write failing MySQL metadata behavior tests**

Cover initialization, default data source/metrics seeding, data-source CRUD, metric CRUD, query logs/feedback/stats, sessions, high-quality historical QA and password sanitization. Use a SQLite-backed fake MySQL connection that translates `%s` placeholders to `?`.

- [x] **Step 2: Verify tests fail**

Run:

```bash
python -m pytest tests/test_meta_mysql.py -q
```

Expected: FAIL because `app.db.meta_mysql` does not exist.

- [x] **Step 3: Implement `MySQLMetaDatabase`**

Subclass `SQLiteDatabase`, create the five MySQL platform tables, override platform metadata methods, and reuse inherited business data-source methods.

- [x] **Step 4: Verify MySQL metadata tests pass**

Run:

```bash
python -m pytest tests/test_meta_mysql.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/db/meta_mysql.py tests/test_meta_mysql.py
git commit -m "feat: add mysql meta database backend"
```

---

### Task 3: SQLite-to-MySQL Metadata Migration Script

**Files:**
- Create: `scripts/migrate_sqlite_meta_to_mysql.py`
- Modify: `tests/test_meta_mysql.py`

- [x] **Step 1: Write failing migration tests**

Create SQLite metadata rows, run the migration function with the fake MySQL backend, and assert rows are copied idempotently with ids, timestamps, feedback and session messages preserved.

- [x] **Step 2: Verify tests fail**

Run:

```bash
python -m pytest tests/test_meta_mysql.py::test_migration_copies_sqlite_metadata_to_mysql_idempotently -q
```

Expected: FAIL because the script does not exist.

- [x] **Step 3: Implement migration script**

Read the five SQLite platform tables and upsert them into MySQL by primary key. Initialize the target first. Sanitize errors.

- [x] **Step 4: Verify migration test passes**

Run the focused migration test. Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/migrate_sqlite_meta_to_mysql.py tests/test_meta_mysql.py
git commit -m "feat: migrate sqlite metadata to mysql"
```

---

### Task 4: Documentation and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/mvp-design.md`
- Modify: `docs/storage-architecture-roadmap.md`
- Modify: `docs/superpowers/plans/2026-07-20-mysql-meta-database.md`

- [x] **Step 1: Update runtime docs**

Document:

```env
META_DB_TYPE=sqlite
META_DATABASE_URL=
META_DB_TYPE=mysql
META_DATABASE_URL=mysql://user:password@localhost:3306/datapilot
```

Document that MySQL database `datapilot` must be created first and that only platform metadata migrates in this phase.

- [x] **Step 2: Run full verification**

Run:

```bash
python -m pytest -q
python scripts/run_evals.py
git diff --check
git status --short --branch
```

Expected: pytest and eval pass; diff check clean.

- [x] **Step 3: Commit docs and plan status**

```bash
git add README.md docs/mvp-design.md docs/storage-architecture-roadmap.md docs/superpowers/plans/2026-07-20-mysql-meta-database.md
git commit -m "docs: document mysql meta database switch"
```

## Final Verification Record (2026-07-20)

- `python -m pytest -q`: 172 passed.
- `python scripts/run_evals.py`: Eval passed 7/7; synthetic RAG wiring smoke off 0/3, on 3/3.
- `git diff --check`: clean.
- A real local migration to MySQL `127.0.0.1:3306/datapilot` succeeded: `data_sources=7`, `metrics=6`, `query_logs=27`, `chat_sessions=22`, `chat_messages=20`.
