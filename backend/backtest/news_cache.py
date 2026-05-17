"""
M4.6 信号新闻特征缓存。

对每条历史 Signal，按 (symbol, date) 查 NewsItem 取近 3 天标题 →
调 analyze_news() → 持久化到 JSON 文件，避免重复 LLM 成本。

设计：
  • 缓存键：f"{symbol}|{date}"
  • 值：{"sentiment", "summary", "impact", "key_events"}
  • 落地位置：backend/backtest/.signal_news_cache.json（git 忽略）
  • cache miss 时按需调 analyze_news()
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent / ".signal_news_cache.json"


def _load_cache() -> dict[str, dict]:
    """从 JSON 文件加载缓存"""
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("缓存文件损坏 %s: %s", _CACHE_FILE, e)
        return {}


def _save_cache(cache: dict[str, dict]) -> None:
    """写回 JSON 文件（pretty 便于人读）"""
    _CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cache_key(symbol: str, date: str) -> str:
    return f"{symbol}|{date}"


def _fetch_titles(symbol: str, date: str, db, lookback_days: int = 3) -> list[str]:
    """查 NewsItem：signal_date 前 lookback_days 天到 signal_date 当天的标题"""
    from backend.data.database import NewsItem

    try:
        end = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)
        start = end - timedelta(days=lookback_days + 1)
    except ValueError:
        return []

    rows = (
        db.query(NewsItem.title)
        .filter(
            NewsItem.symbol == symbol,
            NewsItem.published_at >= start,
            NewsItem.published_at < end,
        )
        .order_by(NewsItem.published_at.desc())
        .limit(15)
        .all()
    )
    return [r[0] for r in rows if r[0]]


def get_or_backfill(
    symbol: str,
    date: str,
    db,
    *,
    use_llm: bool = False,
    lookback_days: int = 3,
) -> dict:
    """
    返回 (symbol, date) 对应的 sentiment_result 字典。

    cache 命中 → 直接返回缓存。
    cache miss + use_llm=True → 查新闻 + 调 analyze_news() → 写回缓存。
    cache miss + use_llm=False → 返回 fallback（不调用 LLM）。

    返回字典结构（与 analyze_news() 兼容）：
      {sentiment: float, summary: str, impact: str, key_events: list[str]}
    """
    cache = _load_cache()
    key = _cache_key(symbol, date)
    if key in cache:
        return cache[key]

    if not use_llm:
        return {"sentiment": 0.0, "summary": "cache miss", "impact": "short", "key_events": []}

    titles = _fetch_titles(symbol, date, db, lookback_days=lookback_days)
    if not titles:
        result = {
            "sentiment": 0.0,
            "summary": "无相关新闻",
            "impact": "short",
            "key_events": [],
        }
    else:
        from backend.analysis.sentiment import analyze_news
        result = analyze_news(titles, symbol=symbol)

    # 写回缓存（即使是空结果也缓存，避免每次都重查 NewsItem）
    cache[key] = result
    _save_cache(cache)
    return result


def backfill_all(
    signals: list,            # list[Signal]
    db,
    *,
    lookback_days: int = 3,
    skip_existing: bool = True,
) -> dict[str, int]:
    """
    批量回填：对每条 Signal 跑 get_or_backfill(use_llm=True)。
    返回 {新增: int, 已存在: int, 无新闻: int, llm_失败: int}。
    """
    cache = _load_cache()
    stats = {"new": 0, "existing": 0, "no_news": 0, "llm_fail": 0}

    for s in signals:
        key = _cache_key(s.symbol, s.date)
        if skip_existing and key in cache:
            stats["existing"] += 1
            continue

        titles = _fetch_titles(s.symbol, s.date, db, lookback_days=lookback_days)
        if not titles:
            cache[key] = {
                "sentiment": 0.0, "summary": "无相关新闻",
                "impact": "short", "key_events": [],
            }
            stats["no_news"] += 1
            continue

        try:
            from backend.analysis.sentiment import analyze_news
            result = analyze_news(titles, symbol=s.symbol)
            if not result.get("key_events") and result.get("summary") == "解析失败":
                stats["llm_fail"] += 1
            cache[key] = result
            stats["new"] += 1
        except Exception as e:
            logger.warning("分析失败 %s %s: %s", s.symbol, s.date, e)
            stats["llm_fail"] += 1

    _save_cache(cache)
    return stats


def clear_cache() -> None:
    """删除缓存文件（测试 / 调试用）"""
    if _CACHE_FILE.exists():
        _CACHE_FILE.unlink()


def cache_path() -> str:
    """返回缓存文件路径（CLI 显示用）"""
    return str(_CACHE_FILE)
