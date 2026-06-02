"""个股新闻抓取：AkShare stock_news_em（A股）/ RSS（美股，Phase 7）"""
import functools
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

# M19.4 时区常量：东财 API 返回 CST（UTC+8）naive 时间字符串
_CST_OFFSET = timedelta(hours=8)


def _cst_to_utc(dt: datetime) -> datetime:
    """将东财 CST naive datetime 转为 UTC naive datetime（减 8 小时）。"""
    return dt - _CST_OFFSET

logger = logging.getLogger(__name__)


def _retry(max_attempts: int = 3, delay: float = 1.0):
    """Retry decorator factory with exponential backoff for news fetchers."""
    def decorator(fn):
        """Inner decorator."""
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            """Wrapped function with retry logic."""
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        logger.warning("%s 最终失败: %s", fn.__name__, e)
                        return []
                    wait = delay * (2 ** attempt)
                    logger.warning("%s 失败（第%d次），%.1fs后重试: %s",
                                   fn.__name__, attempt + 1, wait, e)
                    time.sleep(wait)
        return wrapper
    return decorator


@dataclass
class RawNews:
    title: str
    url: str
    published_at: datetime
    source: str
    symbol: str | None = None


ANSPIRE_SEARCH_URL = "https://plugin.anspire.cn/api/ntsearch/search"
_ANSPIRE_WEAK_HINTS = (
    "股吧", "雪球", "论坛", "问答", "知道", "贴吧", "抖音", "快手", "视频",
    "财富号", "研报精选", "财务摘要", "公司公告_新浪", "行情", "F10", "资料", "企查查",
    "投资分析报告", "深度投资分析",
    "baijiahao", "guba", "xueqiu", "douyin", "kuaishou", "zhihu",
    "caifuhao", "qcc.com", "ttchagu.com", "9fzt.com", "quote",
)
_ANSPIRE_EVENT_HINTS = (
    "公告", "业绩", "营收", "净利", "增长", "亏损", "回购", "减持", "增持",
    "分红", "中标", "订单", "签约", "收购", "并购", "投资", "募资", "扩产",
    "量产", "涨停", "跌停", "立案", "处罚", "问询", "澄清", "评级", "目标价",
    "股东", "解禁", "停牌", "复牌", "海外", "供应", "产品",
)


def _domain_from_url(url: str) -> str:
    """Return a stable domain label for source auditing."""
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _parse_anspire_date(value: str | None, fallback: datetime) -> datetime:
    """Parse Anspire result date strings, falling back to now."""
    if not value:
        return fallback
    raw = str(value).strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return fallback


def _anspire_has_identity(title: str, content: str, symbol: str, name: str) -> bool:
    text = f"{title} {content}"
    return symbol in text or name in text


def _anspire_is_noise(title: str, url: str, source: str) -> bool:
    blob = f"{title} {url} {source}".lower()
    return any(hint.lower() in blob for hint in _ANSPIRE_WEAK_HINTS)


def _anspire_is_event_title(title: str) -> bool:
    return any(hint in title for hint in _ANSPIRE_EVENT_HINTS)


# ── A股个股新闻（东财）──────────────────────────────────────────────

def _fetch_news_df(symbol: str):
    """
    直连东财搜索 API（Session trust_env=False 绕过系统代理），pageSize=50。
    失败时 fallback 到 AkShare stock_news_em（pageSize=10）。
    """
    import json as _json

    import pandas as pd
    import requests

    _CB = "jQuery_stocksage"
    inner = {
        "uid": "", "keyword": symbol,
        "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default", "sort": "default",
                "pageIndex": 1, "pageSize": 50,
                "preTag": "", "postTag": "",
            }
        },
    }
    try:
        session = requests.Session()
        session.trust_env = False
        resp = session.get(
            "https://search-api-web.eastmoney.com/search/jsonp",
            params={"cb": _CB, "param": _json.dumps(inner, ensure_ascii=False), "_": "1"},
            headers={
                "Referer": "https://so.eastmoney.com/",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.text.strip()
        if raw.startswith(_CB):
            raw = raw[len(_CB):].strip("();")
        data = _json.loads(raw)
        articles = data.get("result", {}).get("cmsArticleWebOld", [])
        if articles:
            df = pd.DataFrame(articles)
            df["新闻链接"] = "http://finance.eastmoney.com/a/" + df["code"] + ".html"
            df = df.rename(columns={
                "date": "发布时间", "mediaName": "文章来源",
                "title": "新闻标题", "content": "新闻内容",
            })
            for col in ["新闻标题", "新闻内容"]:
                if col in df.columns:
                    df[col] = df[col].str.replace(r"</?em>", "", regex=True)
            return df[["新闻标题", "新闻链接", "发布时间", "文章来源"]]
    except Exception as e:
        logger.warning("direct news API failed for %s: %s, fallback to AkShare", symbol, e)

    # fallback with retry
    import akshare as ak
    for attempt in range(3):
        try:
            return ak.stock_news_em(symbol=symbol)
        except Exception as e2:
            if attempt == 2:
                logger.warning("AkShare news fallback also failed for %s: %s", symbol, e2)
                return None
            time.sleep(1.5 * (2 ** attempt))


def fetch_stock_news_cn(symbol: str, limit: int = 20) -> list[RawNews]:
    """
    用 AkShare stock_news_em 拉取A股个股新闻。
    symbol: 6位代码，如 "600519"。
    返回最新 limit 条，失败时返回空列表。
    """
    df = _fetch_news_df(symbol)
    if df is None or (hasattr(df, '__len__') and len(df) == 0):
        return []

    results: list[RawNews] = []
    seen_urls: set[str] = set()

    for _, row in df.head(limit).iterrows():
        try:
            title = str(row.get("新闻标题", "")).strip()
            url = str(row.get("新闻链接", "")).strip()
            source = str(row.get("文章来源", "东财")).strip()

            # 无链接时用 symbol+title 的 hash 生成稳定唯一 URL
            if not url or url == "nan":
                digest = hashlib.md5(title.encode()).hexdigest()[:8]  # noqa: S324 - stable local URL key.
                url = f"em://{symbol}#{digest}"

            if url in seen_urls or not title:
                continue
            seen_urls.add(url)

            pub_str = str(row.get("发布时间", "")).strip()
            try:
                # M19.4 时区修复：东财返回 CST naive 时间，统一转为 UTC naive 存储
                pub_dt = _cst_to_utc(datetime.strptime(pub_str, "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                pub_dt = datetime.now(UTC).replace(tzinfo=None)

            results.append(RawNews(
                title=title,
                url=url,
                published_at=pub_dt,
                source=source,
                symbol=symbol,
            ))
        except Exception:
            continue

    return results


# ── 美股 RSS（Phase 7 占位，保留骨架）──────────────────────────────

_US_RSS_FEEDS = [
    ("Yahoo Finance", "https://finance.yahoo.com/rss/"),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
]


def fetch_stock_news_us(symbol: str | None = None, limit: int = 20) -> list[RawNews]:
    """美股新闻（RSS，Phase 7 接入）"""
    try:
        import feedparser
    except ImportError:
        return []

    results: list[RawNews] = []
    for source, url in _US_RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:limit]:
            try:
                pub = (
                    datetime(*entry.published_parsed[:6])
                    if getattr(entry, "published_parsed", None)
                    else datetime.now(UTC).replace(tzinfo=None)
                )
                results.append(RawNews(
                    title=entry.title,
                    url=entry.link,
                    published_at=pub,
                    source=source,
                    symbol=symbol,
                ))
            except Exception:
                continue
    return results


# ── DB 工具 ────────────────────────────────────────────────────────

def save_news_to_db(news_list: list[RawNews], db) -> int:
    """
    批量写入新闻到 news 表，按 URL 去重（已存在的跳过）。
    返回本次新增条数。
    """
    from backend.data.database import NewsItem

    if not news_list:
        return 0

    urls = [n.url for n in news_list]
    existing_urls = {
        r[0] for r in db.query(NewsItem.url).filter(NewsItem.url.in_(urls)).all()
    }

    # M19.4 跨源去重：同标题（不同来源/URL）只保留第一条，避免东财+Anspire重复计入
    seen_title_hashes: set[str] = set()
    new_items = []
    for n in news_list:
        if n.url in existing_urls:
            continue
        title_hash = hashlib.md5(  # noqa: S324 - batch dedup key, not security-sensitive.
            n.title.lower().strip().encode()
        ).hexdigest()[:12]
        if title_hash in seen_title_hashes:
            continue
        seen_title_hashes.add(title_hash)
        new_items.append(NewsItem(
            symbol=n.symbol,
            title=n.title,
            url=n.url,
            published_at=n.published_at,
            source=n.source,
        ))

    if new_items:
        db.bulk_save_objects(new_items)
        db.commit()

    return len(new_items)


def get_recent_titles(symbol: str, db, hours: int = 24) -> list[str]:
    """
    读取该股最近 hours 小时内的新闻标题，供情感分析使用。
    最多返回 15 条（sentiment.py 上限）。
    """
    from backend.data.database import NewsItem

    # M19.4：DB 存储的是 UTC naive，用 UTC now 计算 cutoff
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
    rows = (
        db.query(NewsItem.title)
        .filter(NewsItem.symbol == symbol, NewsItem.published_at >= cutoff)
        .order_by(NewsItem.published_at.desc())
        .limit(15)
        .all()
    )
    return [r[0] for r in rows]


def get_recent_news_items(symbol: str, db, hours: int = 24) -> list[RawNews]:
    """
    读取该股最近 hours 小时内的新闻条目，保留 URL/source/time 供来源审计。
    最多返回 30 条。
    """
    from backend.data.database import NewsItem

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
    rows = (
        db.query(NewsItem)
        .filter(NewsItem.symbol == symbol, NewsItem.published_at >= cutoff)
        .order_by(NewsItem.published_at.desc())
        .limit(30)
        .all()
    )
    return [
        RawNews(
            title=r.title,
            url=r.url,
            published_at=r.published_at,
            source=r.source,
            symbol=r.symbol,
        )
        for r in rows
    ]


def fetch_stock_news_anspire(
    symbol: str,
    name: str,
    *,
    days: int | None = None,
    max_results: int | None = None,
    limit: int | None = None,
    now: datetime | None = None,
) -> list[RawNews]:
    """
    用 Anspire Search 严格补充事件型新闻。

    只返回命中公司身份、看起来像事件新闻、且通过来源审计的条目；
    行情页/F10/资料页/财富号/研报聚合等搜索噪音会被丢弃。
    """
    from backend.config import settings

    if not settings.anspire_api_key:
        return []

    current = now or datetime.now(UTC).replace(tzinfo=None)
    days = days or settings.anspire_news_days
    max_results = max_results or settings.anspire_news_max_results
    limit = limit or settings.anspire_news_max_add
    start = current - timedelta(days=days)

    import json as _json

    import requests

    params = {
        "query": f"{name} {symbol} A股 最新消息 公告 业绩 订单 减持 立案 回购",
        "top_k": str(max_results),
        "search_type": "web",
        "FromTime": start.strftime("%Y-%m-%d 00:00:00"),
        "ToTime": current.strftime("%Y-%m-%d 23:59:59"),
    }
    headers = {
        "Authorization": f"Bearer {settings.anspire_api_key}",
        "Accept": "*/*",
    }

    try:
        resp = requests.get(ANSPIRE_SEARCH_URL, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if isinstance(results, str):
            try:
                results = _json.loads(results)
            except _json.JSONDecodeError:
                results = []
    except Exception as e:
        logger.warning("Anspire news fetch failed for %s: %s", symbol, e)
        return []

    if not isinstance(results, list):
        return []

    items: list[RawNews] = []
    seen_urls: set[str] = set()
    for result in results:
        title = str(result.get("title") or "").strip()
        content = str(result.get("content") or "").strip()
        url = str(result.get("url") or "").strip()
        source = _domain_from_url(url) or "anspire"
        if not title or not url or url in seen_urls:
            continue
        if not _anspire_has_identity(title, content, symbol, name):
            continue
        if _anspire_is_noise(title, url, source):
            continue
        if not _anspire_is_event_title(title):
            continue
        seen_urls.add(url)
        items.append(RawNews(
            title=title,
            url=url,
            published_at=_parse_anspire_date(result.get("date"), current),
            source=source,
            symbol=symbol,
        ))

    if not items:
        return []

    from backend.data.news_audit import audit_news_items

    audits = audit_news_items(
        items,
        now=current,
        min_score=settings.anspire_news_min_score,
    )
    return [audit.news for audit in audits if audit.usable][:limit]


def search_titles_tavily(query: str, days: int = 1, max_results: int = 5) -> list[str]:
    """
    用 Tavily Search API 搜索任意 query 的最新资讯标题。
    需要在 .env 中配置 TAVILY_API_KEY。
    返回标题列表（空列表表示未启用或失败）。
    """
    from backend.config import settings
    if not settings.tavily_api_key:
        return []

    import requests
    try:
        session = requests.Session()
        session.trust_env = False
        resp = session.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "days": days,
                "include_answer": False,
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [r["title"] for r in results if r.get("title")]
    except Exception as e:
        logger.warning("Tavily news fetch failed for query=%s: %s", query, e)
        return []


def fetch_titles_tavily(symbol: str, name: str, days: int = 1, max_results: int = 5) -> list[str]:
    """
    用 Tavily Search API 搜索该股最新资讯标题。
    DB 新闻不足时作为补充，返回标题列表（空列表表示未启用或失败）。
    """
    return search_titles_tavily(f"{name} {symbol} 股票 最新消息", days=days, max_results=max_results)
