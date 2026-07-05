# Alembic 已退役（DORMANT）

**权威 schema 路径 = `backend/data/database.py::init_db()`**
（`Base.metadata.create_all` + `_ensure_runtime_schema`），启动时由 `backend/main.py` 调用。

本目录的 Alembic 迁移**不再是本项目的 schema 权威路径**，启动链不调用
`alembic upgrade`，CI 也不跑它。保留这些文件仅作历史记录。

schema 漂移由 `tests/test_schema_authority.py` 的 golden 快照守卫强制把关：
任何 ORM 模型或 `schema_runtime.py` 裸 DDL 的改动都会让它变红，须显式重生成 golden。

若未来迁到 Postgres 需要版本化迁移，再评估是否复活 Alembic 或换方案。
