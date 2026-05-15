"""LLM 新闻情感分析"""
import hashlib
from backend.llm import get_provider

_cache: dict[str, dict] = {}  # 进程内缓存，避免相同新闻重复调用 API

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

_FALLBACK = {"sentiment": 0.0, "summary": "无相关新闻", "impact": "short", "key_events": []}


def _titles_hash(titles: list[str]) -> str:
    """Return MD5 hex digest of sorted title list for cache keying."""
    return hashlib.md5("|".join(sorted(titles)).encode()).hexdigest()


def analyze_news(titles: list[str], symbol: str | None = None) -> dict:
    """
    输入新闻标题列表，返回情感分析结果。
    {sentiment: float, summary: str, impact: str, key_events: list}
    相同标题集合在进程生命周期内只调用一次 API。
    """
    if not titles:
        return _FALLBACK.copy()

    cache_key = _titles_hash(titles)
    if cache_key in _cache:
        return _cache[cache_key]

    context = f"股票代码：{symbol}\n" if symbol else ""
    prompt = context + "新闻标题：\n" + "\n".join(f"- {t}" for t in titles[:15])

    data = get_provider().complete_structured(
        prompt=prompt,
        tool=_SENTIMENT_TOOL,
        system=SYSTEM_PROMPT,
        max_tokens=300,
        model_tier="fast",
    )

    if not data:
        return {"sentiment": 0.0, "summary": "解析失败", "impact": "short", "key_events": []}

    data["sentiment"] = max(-1.0, min(1.0, float(data.get("sentiment", 0))))
    data["key_events"] = data.get("key_events", [])[:3]
    _cache[cache_key] = data
    return data
