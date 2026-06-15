"""LLM 新闻情感分析"""
import hashlib
import json
from collections import OrderedDict
from datetime import UTC, datetime

from backend.analysis.event_taxonomy import apply_event_score, company_specific_titles
from backend.config import settings
from backend.llm import get_provider, has_runtime_llm_provider

_CACHE_MAX_SIZE = 256
_cache: OrderedDict[str, dict] = OrderedDict()  # 进程内 LRU 缓存，避免相同新闻重复调用 API

SYSTEM_PROMPT = "你是专业的A股新闻分析师。分析新闻标题列表，评估对股票的短期情感影响。sentiment范围-1.0到1.0，key_events最多3条。"

_SENTIMENT_TOOL = {
    "name": "record_sentiment",
    "description": "记录新闻情感分析结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "sentiment": {
                "type": "number",
                "description": "-1.0(极度负面) 到 1.0(极度正面)",
            },
            "summary": {"type": "string", "description": "50字内中文摘要"},
            "impact": {
                "type": "string",
                "enum": ["short", "medium", "long"],
                "description": "预计影响周期",
            },
            "key_events": {
                "type": "array",
                "items": {"type": "string"},
                "description": "关键事件列表（最多3条）",
            },
        },
        "required": ["sentiment", "summary", "impact", "key_events"],
    },
}

_FALLBACK = {
    "sentiment": 0.0,
    "summary": "无相关新闻",
    "impact": "short",
    "key_events": [],
    "event_score": 0.0,
    "event_score_mode": "sentiment_fallback",
    "event_types": [],
}
_DISABLED_FALLBACK = {
    "sentiment": 0.0,
    "summary": "LLM已禁用",
    "impact": "short",
    "key_events": [],
    "event_score": 0.0,
    "event_score_mode": "sentiment_fallback",
    "event_types": [],
}
# Evidence floor: when a symbol's window has no company-specific headline (only
# sector/fund-flow/list noise), neutralise sentiment instead of scoring noise.
# Prevents the M27 whipsaw (e.g. 兆易 603986: 2 sector-IPO headlines, 0 company
# news → -71.3 sentiment). Skips the LLM call entirely, so it is also cheaper.
_NOISE_ONLY_FALLBACK = {
    "sentiment": 0.0,
    "summary": "仅板块/资金流新闻，无个股特定信号，情感置中",
    "impact": "short",
    "key_events": [],
    "low_confidence": True,
    "event_score": 0.0,
    "event_score_mode": "evidence_floor",
    "event_types": [],
}


def _titles_hash(titles: list[str]) -> str:
    """Return the stable legacy digest used for sentiment-cache keying."""
    return hashlib.md5(  # noqa: S324 - legacy cache key, not a security digest.
        "|".join(sorted(titles[:15])).encode()
    ).hexdigest()


def _cache_key(titles: list[str], symbol: str | None = None) -> tuple[str, str]:
    titles_hash = _titles_hash(titles)
    return f"{symbol or '*'}:{titles_hash}", titles_hash


def _cache_get(key: str) -> dict | None:
    """Return a copy of cached data and refresh LRU order."""
    if key not in _cache:
        return None
    value = _cache.pop(key)
    _cache[key] = value
    return dict(value)


def _cache_set(key: str, value: dict) -> None:
    """Store a copy in bounded LRU cache."""
    _cache[key] = dict(value)
    while len(_cache) > _CACHE_MAX_SIZE:
        _cache.popitem(last=False)


def _ensure_persistent_cache_schema() -> None:
    from sqlalchemy import text

    from backend.data.database import engine

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sentiment_cache (
                cache_key TEXT PRIMARY KEY,
                symbol TEXT,
                titles_hash TEXT,
                result_json TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_sentiment_cache_symbol_hash
            ON sentiment_cache(symbol, titles_hash)
        """))


def _persistent_cache_get(key: str) -> dict | None:
    try:
        _ensure_persistent_cache_schema()
        from backend.data.database import SentimentCache, SessionLocal

        db = SessionLocal()
        try:
            row = db.query(SentimentCache).filter(SentimentCache.cache_key == key).first()
            if not row:
                return None
            data = json.loads(row.result_json)
            if isinstance(data, dict):
                return data
            return None
        finally:
            db.close()
    except Exception:
        return None


def _persistent_cache_set(key: str, titles_hash: str, symbol: str | None, value: dict) -> None:
    try:
        _ensure_persistent_cache_schema()
        from backend.data.database import SentimentCache, SessionLocal

        db = SessionLocal()
        try:
            now = datetime.now(UTC).replace(tzinfo=None)
            payload = json.dumps(value, ensure_ascii=False)
            row = db.query(SentimentCache).filter(SentimentCache.cache_key == key).first()
            if row:
                row.result_json = payload
                row.updated_at = now
            else:
                db.add(SentimentCache(
                    cache_key=key,
                    symbol=symbol,
                    titles_hash=titles_hash,
                    result_json=payload,
                    created_at=now,
                    updated_at=now,
                ))
            db.commit()
        finally:
            db.close()
    except Exception:
        return


def analyze_news(
    titles: list[str],
    symbol: str | None = None,
    company_aliases: list[str] | None = None,
) -> dict:
    """
    输入新闻标题列表，返回情感分析结果。
    {sentiment: float, summary: str, impact: str, key_events: list}
    相同股票+标题集合优先命中进程内和 SQLite 缓存，避免重复消耗 LLM 配额。
    company_aliases（股票名/代码等别名）用于个股相关性过滤与证据地板；不传则只过滤行情/资金流噪声。
    """
    if not titles:
        return apply_event_score(_FALLBACK, [])
    if not has_runtime_llm_provider(settings):
        return apply_event_score(_DISABLED_FALLBACK, titles)
    # Evidence floor: no company-specific headline (only noise / cross-company) → neutral, skip LLM.
    analysis_titles = company_specific_titles(titles, company_aliases)
    if not analysis_titles:
        return dict(_NOISE_ONLY_FALLBACK)

    cache_key, titles_hash = _cache_key(analysis_titles, symbol)
    cached = _cache_get(cache_key)
    if cached is not None:
        return apply_event_score(cached, analysis_titles)
    cached = _persistent_cache_get(cache_key)
    if cached is not None:
        _cache_set(cache_key, cached)
        return apply_event_score(cached, analysis_titles)

    context = f"股票代码：{symbol}\n" if symbol else ""
    prompt = context + "新闻标题：\n" + "\n".join(f"- {t}" for t in analysis_titles[:15])

    data = get_provider().complete_structured(
        prompt=prompt,
        tool=_SENTIMENT_TOOL,
        system=SYSTEM_PROMPT,
        max_tokens=300,
        model_tier="fast",
    )
    try:
        import json as _json

        from backend.ops.llm_usage import log_llm_usage
        log_llm_usage("sentiment", SYSTEM_PROMPT + prompt, _json.dumps(data))
    except Exception:
        pass

    if not data:
        return apply_event_score({
            "sentiment": 0.0,
            "summary": "解析失败",
            "impact": "short",
            "key_events": [],
            "event_score": 0.0,
            "event_score_mode": "sentiment_fallback",
            "event_types": [],
        }, analysis_titles)

    data["sentiment"] = max(-1.0, min(1.0, float(data.get("sentiment", 0))))
    data["key_events"] = data.get("key_events", [])[:3]
    data = apply_event_score(data, analysis_titles)
    _cache_set(cache_key, data)
    _persistent_cache_set(cache_key, titles_hash, symbol, data)
    return dict(data)
