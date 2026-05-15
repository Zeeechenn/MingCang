"""
Point-in-Time (PIT) 数据访问拦截层（Tier 3）

为什么需要：
  • 长期 label TTL 用 expires_at 控制了"使用窗口"，但**回测**时仍能读到 > as_of 的标签
  • FinancialMetric.report_date 在回测中可能被未来季度污染
  • Look-Ahead-Bench (Benhenda 2026) 指出这是 LLM/quant 系统最常见的隐性 bug

设计：
  • PITSession 是 db session 的薄包装
  • 拦截 .query(Model) — 根据 model 自动加 date / report_date / published_at 上界过滤
  • 不修改 ORM 模型本体，不动主流程；回测代码显式用 PITSession 包装
  • 主流程（盘后 job 等）使用裸 SessionLocal，性能/语义不变

用法：
    from backend.data.point_in_time import pit_session
    with pit_session(SessionLocal(), as_of="2024-10-01") as db:
        signals = db.query(Signal).all()   # 自动 filter Signal.date <= "2024-10-01"
"""
from __future__ import annotations
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

logger = logging.getLogger(__name__)


# 各 ORM 模型对应的"时间字段名"
# 若 model 未在此 map 中，PITSession 不会拦截（透传）。
_PIT_DATE_FIELDS: dict[str, tuple[str, str]] = {
    "Price": ("date", "string"),
    "Signal": ("date", "string"),
    "LongTermLabel": ("date", "string"),
    "FinancialMetric": ("report_date", "string"),
    "IndexPrice": ("date", "string"),
    "NewsItem": ("published_at", "datetime"),
}


class PITSession:
    """
    包装 SQLAlchemy Session，强制所有受管 model 查询过滤 date <= as_of。

    其他属性透传给底层 db。
    """

    def __init__(self, db, as_of: str) -> None:
        """Wrap db session with a point-in-time cutoff date."""
        self._db = db
        self._as_of = as_of

    @property
    def as_of(self) -> str:
        """Return the as-of cutoff date string."""
        return self._as_of

    def query(self, *entities, **kwargs) -> Any:
        """Intercept query and apply date filter for registered PIT models."""
        q = self._db.query(*entities, **kwargs)
        for ent in entities:
            cls_name = getattr(ent, "__name__", None)
            if cls_name in _PIT_DATE_FIELDS:
                field_name, field_kind = _PIT_DATE_FIELDS[cls_name]
                col = getattr(ent, field_name)
                if field_kind == "datetime":
                    cutoff = datetime.fromisoformat(self._as_of)
                    q = q.filter(col <= cutoff)
                else:
                    q = q.filter(col <= self._as_of)
        return q

    def __getattr__(self, name) -> Any:
        """Delegate all other attribute access to the underlying db session."""
        return getattr(self._db, name)


@contextmanager
def pit_session(db, as_of: str) -> Iterator["PITSession"]:
    """上下文管理器版本。"""
    yield PITSession(db, as_of)


def assert_pit_clean(db, as_of: str, model, field: str | None = None) -> int:
    """
    审计辅助：返回若不过滤会泄漏的行数（> as_of）。
    主要在集成测试中使用：assert_pit_clean(..., model=Price) == 0。
    """
    cls_name = getattr(model, "__name__", None)
    if cls_name not in _PIT_DATE_FIELDS and not field:
        raise ValueError(f"未知 PIT 字段：{cls_name}")
    fld, kind = _PIT_DATE_FIELDS.get(cls_name, (field, "string"))
    col = getattr(model, fld)
    if kind == "datetime":
        cutoff = datetime.fromisoformat(as_of)
        return db.query(model).filter(col > cutoff).count()
    return db.query(model).filter(col > as_of).count()
