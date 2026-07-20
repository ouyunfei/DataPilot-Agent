# MySQL 元数据库兼容切换设计

## 1. 背景

DataPilot 当前用 `SQLiteDatabase` 同时承担两类职责：

- 平台元数据：`data_sources`、`metrics`、`query_logs`、`chat_sessions`、`chat_messages`。
- 默认演示业务库：`orders`、`users`、`products`。

`docs/storage-architecture-roadmap.md` 的阶段二要求把平台配置、日志、会话和指标切到 MySQL 元数据库，并保留 SQLite 回滚路径。用户确认本阶段采用兼容切换：默认仍用 SQLite；配置 `META_DB_TYPE=mysql` 和 `META_DATABASE_URL` 后，平台元数据读写切到 MySQL。后续目标存储只保留 MySQL、Qdrant、Redis；但本阶段不删除现有 SQLite/PostgreSQL 查询适配，避免一次改动过大。

用户指定 MySQL 数据库名称使用项目名：

```text
datapilot
```

## 2. 目标

1. 新增 MySQL 元数据库运行路径。
2. 默认不配置时继续使用现有 SQLite 行为。
3. 配置 MySQL 后，以下平台表在 MySQL `datapilot` 库中创建和读写：
   - `data_sources`
   - `metrics`
   - `query_logs`
   - `chat_sessions`
   - `chat_messages`
4. 保留现有 API、Agent 调用方式和响应结构。
5. 提供一次性迁移脚本，将 SQLite 平台元数据迁移到 MySQL。
6. 不泄露 MySQL 密码到 API、日志或脚本错误输出。

## 3. 非目标

- 不开发前端。
- 不接入 Redis。
- 不迁移 Qdrant 数据。
- 不迁移 `orders/users/products` 业务表。
- 不删除 SQLite 代码。
- 不删除 PostgreSQL/MySQL/SQLite 业务数据源适配。
- 不新增通用 ORM、Repository 框架或多数据库抽象层。

这些留到后续“关系型数据库收敛”和“按需 Redis”阶段。

## 4. 配置

新增配置项：

```env
META_DB_TYPE=sqlite
META_DATABASE_URL=
```

MySQL 模式示例：

```env
META_DB_TYPE=mysql
META_DATABASE_URL=mysql://user:password@localhost:3306/datapilot
```

规则：

- `META_DB_TYPE` 缺省或为 `sqlite`：使用现有 `SQLiteDatabase(DEFAULT_DATABASE_PATH)`。
- `META_DB_TYPE=mysql`：使用 MySQL 元数据库。
- `META_DB_TYPE` 其他值：启动失败并提示只支持 `sqlite` 或 `mysql`。
- `META_DB_TYPE=mysql` 但 `META_DATABASE_URL` 为空：启动失败。

## 5. 架构

最小文件范围：

```text
app/core/config.py       # 增加 META_DB_TYPE / META_DATABASE_URL
app/db/meta_mysql.py     # 新增 MySQLMetaDatabase
app/main.py              # 根据配置选择 SQLiteDatabase 或 MySQLMetaDatabase
scripts/migrate_sqlite_meta_to_mysql.py
.env.example
README.md
docs/mvp-design.md
docs/storage-architecture-roadmap.md
tests/
```

`DataAnalysisAgent` 和 `app/api/routes.py` 继续调用同一组方法：

```python
list_data_sources()
get_data_source()
get_default_data_source()
create_data_source()
update_data_source()
delete_data_source()
list_metrics()
create_metric()
update_metric()
delete_metric()
log_query()
list_query_logs()
update_query_feedback()
list_high_quality_historical_qa()
create_session()
save_chat_message()
get_recent_session_context()
get_query_stats()
```

`MySQLMetaDatabase` 只替换平台元数据读写。业务查询能力继续复用现有 `SQLiteDatabase` 的数据源执行逻辑和 `MySQLClient` / `PostgresClient` 适配逻辑。

为避免大重构，MySQL 模式仍会保留默认 SQLite 演示库文件作为回滚和演示路径，但默认数据源本身会切到 `default_mysql` 并指向 Docker 示例 MySQL。后续如果要完全 MySQL 化，单独迁移业务表并移除 SQLite 默认路径。

## 6. MySQL 表结构

目标库：

```sql
CREATE DATABASE datapilot DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

平台表字段与现有 SQLite 保持兼容。JSON 内容继续以文本保存，减少差异和迁移风险。

### data_sources

```text
id BIGINT AUTO_INCREMENT PRIMARY KEY
name VARCHAR(100) NOT NULL UNIQUE
db_type VARCHAR(32) NOT NULL
database_url TEXT NOT NULL
allowed_tables TEXT NOT NULL
allowed_columns TEXT
is_default TINYINT(1) NOT NULL DEFAULT 0
created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

### metrics

```text
id BIGINT AUTO_INCREMENT PRIMARY KEY
metric_key VARCHAR(64) NOT NULL UNIQUE
name VARCHAR(100) NOT NULL
expression TEXT NOT NULL
description TEXT NOT NULL
enabled TINYINT(1) NOT NULL DEFAULT 1
created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
```

### query_logs

```text
id BIGINT AUTO_INCREMENT PRIMARY KEY
question TEXT NOT NULL
sql TEXT NOT NULL
trusted_answer TINYINT(1) NOT NULL
chart_type VARCHAR(32) NOT NULL
row_count INT NOT NULL
error TEXT
error_code VARCHAR(64)
feedback VARCHAR(16)
feedback_note TEXT
duration_ms INT NOT NULL
data_source_id BIGINT
sql_explanation TEXT NOT NULL
answer TEXT NOT NULL
created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

### chat_sessions

```text
id VARCHAR(64) PRIMARY KEY
created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
```

### chat_messages

```text
id BIGINT AUTO_INCREMENT PRIMARY KEY
session_id VARCHAR(64) NOT NULL
question TEXT NOT NULL
sql TEXT NOT NULL
answer TEXT NOT NULL
created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
INDEX idx_chat_messages_session_id_id (session_id, id)
```

本阶段不强制外键，避免迁移旧数据时因部分历史会话或日志不完整而失败。

## 7. 初始化与默认数据

MySQL 元数据库 `initialize()`：

1. 连接 `META_DATABASE_URL`。
2. 创建 5 张平台表。
3. 若没有默认数据源，插入现有默认 `default_mysql` 数据源；若历史数据还保留 `default_sqlite`，启动时会收敛为 `default_mysql`。
4. 若没有默认指标，插入 `DEFAULT_METRICS`。

MySQL 不自动创建数据库本身。用户需要先在 Navicat 或 SQL 中创建 `datapilot` 库。

## 8. 迁移脚本

新增脚本：

```bash
python scripts/migrate_sqlite_meta_to_mysql.py
```

行为：

- 读取 `DEFAULT_DATABASE_PATH` 的 SQLite 平台表。
- 写入 `META_DATABASE_URL` 指向的 MySQL `datapilot` 库。
- 迁移 5 张平台表，不迁移业务表。
- 使用主键 `id` 做幂等 upsert，重复执行不制造重复数据。
- 保留 `created_at`、`updated_at`、反馈、错误码、SQL 解释和回答。
- 输出每张表迁移数量。
- 错误输出必须隐藏连接密码。

## 9. 数据流

SQLite 默认模式：

```text
FastAPI -> DataAnalysisAgent -> SQLiteDatabase -> data/datapilot.db
```

MySQL 元数据库模式：

```text
FastAPI -> DataAnalysisAgent -> MySQLMetaDatabase -> MySQL datapilot
                                      |
                                      +-> 现有数据源配置决定业务查询库
```

Qdrant RAG 不变：

```text
scripts/rebuild_knowledge_index.py -> db.list_data_sources/list_metrics/list_high_quality_historical_qa -> Qdrant Local
```

配置 MySQL 元数据库后，RAG 重建自然从 MySQL 读取平台知识。

## 10. 错误处理与安全

- MySQL 连接失败时启动失败，错误消息隐藏密码。
- API 返回数据源时继续隐藏 `database_url` 密码。
- 迁移脚本和连接测试不打印完整密码。
- SQL 生成、SQL 校验、表字段白名单、LIMIT 和超时逻辑不变。
- 元数据库账号需要读写平台表；业务数据源账号推荐只给 `SELECT`。

## 11. 测试

最小测试范围：

1. 默认配置仍创建并使用 SQLite。
2. `META_DB_TYPE=mysql` 时 `create_app()` 选择 MySQL 元数据库。
3. MySQL 元数据库初始化会创建 5 张平台表并写入默认指标/默认数据源。
4. 数据源 CRUD、指标 CRUD、日志、反馈、会话、统计在 MySQL 元数据库下行为与 SQLite 一致。
5. 迁移脚本能把 SQLite 平台表复制到 MySQL 写入器，并且重复运行不重复。
6. 错误消息不包含 MySQL 密码。
7. 现有 `pytest`、`scripts/run_evals.py` 继续通过。

测试使用 fake PyMySQL connection，不要求 CI 连接真实 MySQL。

## 12. 验收标准

1. 不配置新环境变量时，现有功能和测试不变。
2. 配置：

```env
META_DB_TYPE=mysql
META_DATABASE_URL=mysql://user:password@localhost:3306/datapilot
```

后，平台元数据读写进入 MySQL。
3. 迁移脚本能把 SQLite 里的平台配置、指标、日志、反馈和会话迁到 MySQL。
4. `/api/chat`、数据源、指标、日志、反馈、统计、RAG 重建入口不需要改 API。
5. 不新增前端、不新增 Redis、不删除 SQLite。
