# Alembic 迁移（MingCang）

引入于 P0-2（`fix/safe-layer`）。目标：让生产 schema 升级**版本化、可回滚**，
取代此前的「`create_all` + 手写 `ALTER TABLE`」。

## 现状与边界（务必先读）

- **target_metadata** = `backend.data.orm.Base.metadata`（31 个 ORM 模型，经
  `backend.data.models` 包注册）。
- `env.py` 的 `include_object` 只管 ORM 表与 ORM 索引；**不碰**非 ORM 表
  （`ai_memory`、`audit_log_fts*`、`sqlite_sequence`）和运行期 `idx_*` 索引
  （仍由 `database.py::_ensure_runtime_schema` 维护）。
- `compare_type=False`：SQLite 类型亲和性使 TEXT/String 比较不可靠，关闭以免噪音。
- DB URL 优先级：`-x dburl=...` > `ALEMBIC_DB_URL` 环境变量 > `settings.database_url`。
  **验证迁移时务必指向临时副本，绝不在生产库原地试。**

## 已验证

- 空库 `upgrade head` → 精确创建 31 张 ORM 表；`downgrade base` → 全部回滚（只剩
  `alembic_version`）。
- 生产库副本 `stamp head` 后 `alembic check`：ORM 表无结构差异，**仅剩历史
  `NOT NULL` 漂移**（部分列在 ORM 标注 NOT NULL，但现网历史建表为 nullable）。
  此漂移**预先存在**（即 `_verify_schema_consistency` 一直告警的内容），非本次引入。

## 待办（后续独立 PR）

1. **修历史 nullable 漂移**：用 Alembic 写一条 reconciliation 迁移，在副本上验证后
   再上现网。这正是引入 Alembic 后才安全可行的事。
2. **切换 init_db**：当前 `init_db` 仍走 `create_all + _ensure_runtime_schema`
   （保证测试与 fresh DB 不变）。若未来改为 `alembic upgrade head` 作为唯一建库路径，
   需先把运行期 `idx_*`/规范化唯一索引并入迁移，否则 fresh DB 会缺这些索引。

## 常用命令

```bash
# 现网首次纳管（标记为已在基线，不改 schema）：
ALEMBIC_DB_URL="sqlite:////path/prod.db" alembic stamp head

# 新增 schema 变更（改完 ORM 模型后）：
alembic revision --autogenerate -m "描述"
# 先在副本验证，再上现网：
ALEMBIC_DB_URL="sqlite:////tmp/copy.db" alembic upgrade head
ALEMBIC_DB_URL="sqlite:////tmp/copy.db" alembic downgrade -1   # 确认可回滚
```
