"""交易日新鲜度门：计算「本轮应期望的最新交易日」，替代"池内max共识基准日"。

背景：全池统一以池内已有数据的max日期作共识基准时，若数据源集体故障导致全池
陈旧，会把陈旧误判为新鲜（因为大家都一样旧）。这里改用外部锚点（prices/
index_prices 表里已确认的最新交易日）+ 收盘后候选日 + 探针三段式判断，不依赖
"多数人一致"这个会被系统性故障污染的信号。
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def expected_trade_date(
    db,
    now: datetime | None = None,
    *,
    probe: bool = True,
    probe_symbol: str = "600519",
) -> tuple[str, str]:
    """返回 (expected_date, basis)，basis 说明该日期是如何得出的。

    basis 取值：
    - "probe": 收盘后候选日通过探针确认已有源给出该日 bar。
    - "probe_failed_anchor": 收盘后候选日探针未确认（源尚未更新/故障），回落到
      锚点（通常即上一交易日）。周中法定节假日也会走这条路径——当天没有真实
      交易，探针自然探不到"节假日"这个候选日的 bar，于是零误报地回落到上一
      交易日锚点，不需要额外维护节假日日历。
    - "candidate": probe=False 时跳过探针，直接采用收盘后候选日（调用方自担
      风险，用于不便做网络探针的场景，如单测）。
    - "anchor": 非收盘后时段（或候选日未超过锚点），采用数据库里已确认的最新
      交易日锚点。
    - "unknown": 锚点与候选日都拿不到（数据库为空且非收盘后），空字符串占位。

    锚点 = prices 表与 index_prices 表里 date 字段（前10位，兼容纯日期与
    "YYYY-MM-DDTHH:MM..." 时间戳格式）的最大值中的更大者；表不存在或为空则忽略。
    """
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Asia/Shanghai")
    now_sh = (now or datetime.now(zone))
    if now_sh.tzinfo is None:
        now_sh = now_sh.replace(tzinfo=zone)
    else:
        now_sh = now_sh.astimezone(zone)

    anchor = _max_anchor_date(db)

    candidate: str | None = None
    if now_sh.weekday() < 5 and (now_sh.hour, now_sh.minute) >= (15, 5):
        candidate = now_sh.date().isoformat()

    if candidate and candidate > (anchor or ""):
        if not probe:
            return candidate, "candidate"
        try:
            from backend.data.providers import fetch_daily_with_fallback

            df, _provider = fetch_daily_with_fallback(
                probe_symbol, "CN", 5, expected_latest=candidate
            )
            latest = None
            if df is not None and not df.empty:
                idx_max = df.index.max()
                latest = idx_max.date().isoformat() if hasattr(idx_max, "date") else str(idx_max)[:10]
            if latest == candidate:
                return candidate, "probe"
            logger.warning(
                "expected_trade_date: 收盘后候选日 %s 探针未确认（探到 %s），回落锚点 %s",
                candidate, latest, anchor,
            )
            return anchor or candidate, "probe_failed_anchor"
        except Exception as e:
            logger.warning(
                "expected_trade_date: 收盘后候选日 %s 探针异常（%s），回落锚点 %s",
                candidate, e, anchor,
            )
            return anchor or candidate, "probe_failed_anchor"

    if anchor:
        return anchor, "anchor"
    return "", "unknown"


def _max_anchor_date(db) -> str | None:
    """返回 prices/index_prices 两表 date 字段（截前10位）的最大值，表不存在/空则忽略。"""
    from sqlalchemy import text

    candidates: list[str] = []
    for table in ("prices", "index_prices"):
        try:
            row = db.execute(text(f"SELECT MAX(substr(date,1,10)) FROM {table}")).first()
        except Exception:
            continue
        if row and row[0]:
            candidates.append(str(row[0]))
    return max(candidates) if candidates else None
