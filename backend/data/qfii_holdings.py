"""
QFII（合格境外机构投资者）前十大流通股东抓取与缓存

数据源：AkShare `stock_gdfx_free_top_10_em`（东方财富）
缓存：~/.stock-sage/qfii_cache/{symbol}.json
  • 一只股票一个文件，键为季度报告期（"20251231"），值为该季 QFII 持仓列表
  • 拉取失败时静默降级（返回空字典），不影响其他长期分析师

QFII 关键词白名单：覆盖外资投行 / 主权基金 / 跨国资管 的中文常用名
  • 高盛 / Goldman
  • 摩根士丹利 / Morgan Stanley
  • 摩根大通 / J.P. Morgan
  • 瑞士联合银行 / 瑞银 / UBS
  • 巴克莱 / Barclays
  • 法国巴黎银行 / BNP
  • 阿布达比投资局 / ADIA
  • 淡马锡 / Temasek
  • 新加坡政府投资 / GIC
  • 挪威银行 / Norges
  • 汇丰 / HSBC
  • 美林 / Merrill
  • 花旗 / Citi
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".stock-sage" / "qfii_cache"

# M19.3 TTL: 季报披露窗口约 120 天（Q4/Q1 由 4/30 截止，Q3 由 10/31）；
# 在窗口内空结果可能只是"尚未披露"，每 7 天重试一次。窗口外的空结果稳定，永久缓存。
DISCLOSURE_WINDOW_DAYS = 120
EMPTY_RESULT_TTL_DAYS = 7

QFII_KEYWORDS = [
    "高盛", "Goldman",
    "摩根士丹利", "Morgan Stanley",
    "摩根大通", "J.P. Morgan", "JP Morgan", "JPMorgan",
    "瑞士联合银行", "瑞银", "UBS",
    "巴克莱", "Barclays",
    "法国巴黎银行", "BNP",
    "阿布达比", "ADIA",
    "淡马锡", "Temasek",
    "新加坡政府投资", "GIC",
    "挪威银行", "Norges",
    "汇丰", "HSBC",
    "美林", "Merrill",
    "花旗", "Citi",
]


def is_qfii_holder(holder_name: str) -> bool:
    """根据关键词判断股东是否为外资 QFII"""
    if not holder_name:
        return False
    return any(kw in holder_name for kw in QFII_KEYWORDS)


def _market_prefix(symbol: str) -> str:
    """A 股 6 位代码 → 东方财富前缀（sh/sz/bj）"""
    if symbol.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{symbol}"
    if symbol.startswith(("000", "001", "002", "003", "300", "301")):
        return f"sz{symbol}"
    if symbol.startswith(("8", "4")):
        return f"bj{symbol}"
    return f"sh{symbol}"


def _recent_quarter_dates(quarters: int, today: date | None = None) -> list[str]:
    """返回最近 N 个已结束季度的报告期，从最近往前排（YYYYMMDD）"""
    today = today or date.today()
    quarter_ends = [(3, 31), (6, 30), (9, 30), (12, 31)]
    out: list[str] = []
    year, month = today.year, today.month
    for m, d in reversed(quarter_ends):
        if (month, 1) > (m, d):
            out.append(f"{year}{m:02d}{d:02d}")
            break
    if not out:
        year -= 1
        out.append(f"{year}1231")
    while len(out) < quarters:
        last = out[-1]
        y, m, d = int(last[:4]), int(last[4:6]), int(last[6:8])
        if (m, d) == (3, 31):
            out.append(f"{y - 1}1231")
        elif (m, d) == (6, 30):
            out.append(f"{y}0331")
        elif (m, d) == (9, 30):
            out.append(f"{y}0630")
        else:
            out.append(f"{y}0930")
    return out


def _fetch_single_quarter(symbol: str, report_date: str) -> list[dict] | None:
    """拉单季 QFII 持仓；失败返回 None，确无 QFII 返回 []。"""
    try:
        import akshare as ak
        df = ak.stock_gdfx_free_top_10_em(symbol=_market_prefix(symbol), date=report_date)
    except Exception as e:
        logger.debug("AkShare 拉取失败 %s %s: %s", symbol, report_date, e)
        return None
    if df is None or df.empty:
        return []
    rows: list[dict] = []
    for _, r in df.iterrows():
        name = str(r.get("股东名称", "")).strip()
        if not is_qfii_holder(name):
            continue
        try:
            shares = int(r.get("持股数") or 0)
        except (TypeError, ValueError):
            shares = 0
        change_raw = str(r.get("增减", "")).strip()
        if change_raw == "不变":
            change = 0
        else:
            try:
                change = int(change_raw.replace(",", ""))
            except (TypeError, ValueError):
                change = None
        rows.append({"holder": name, "shares": shares, "change": change})
    return rows


def _cache_path(symbol: str) -> Path:
    """Return the cache file path for a symbol's QFII holdings."""
    return CACHE_DIR / f"{symbol}.json"


def _read_cache(symbol: str) -> dict[str, object]:
    """Read cached QFII holdings for a symbol, returning empty dict on miss.

    Entries may be:
      • legacy ``list[dict]`` (pre-M19.3 format), or
      • ``{"data": list[dict], "cached_at": "YYYY-MM-DD"}`` with TTL metadata.
    """
    p = _cache_path(symbol)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(symbol: str, data: dict[str, object]) -> None:
    """Write QFII holdings data to the cache file for a symbol."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(symbol).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _entry_data(entry: object) -> list[dict] | None:
    """Extract holdings list from either legacy list or TTL-wrapped dict."""
    if isinstance(entry, list):
        return entry
    if isinstance(entry, dict) and isinstance(entry.get("data"), list):
        return entry["data"]
    return None


def _is_entry_fresh(entry: object, report_date: str, today: date) -> bool:
    """Decide whether a cache entry is still usable or needs refetch.

    Empty results inside the disclosure window expire after ``EMPTY_RESULT_TTL_DAYS``
    so a "report not yet disclosed" cache miss does not get pinned forever.
    """
    data = _entry_data(entry)
    if data is None:
        return False
    if data:
        return True
    try:
        rd = datetime.strptime(report_date, "%Y%m%d").date()
    except ValueError:
        return True
    if today - rd >= timedelta(days=DISCLOSURE_WINDOW_DAYS):
        return True
    if isinstance(entry, dict):
        cached_at_raw = entry.get("cached_at")
        if isinstance(cached_at_raw, str):
            try:
                cached_at = date.fromisoformat(cached_at_raw)
            except ValueError:
                return False
            return today - cached_at < timedelta(days=EMPTY_RESULT_TTL_DAYS)
    return False


def get_qfii_history(symbol: str, quarters: int = 4,
                     today: date | None = None,
                     fetcher=_fetch_single_quarter) -> dict[str, list[dict]]:
    """
    获取近 quarters 个季度的 QFII 持仓快照。

    返回 {"20251231": [{"holder": "高盛集团", "shares": 1234567, "change": -200000}, ...], ...}
    报告期键按时间倒序（最近季度在前）。

    fetcher 参数用于测试时注入 mock。

    M19.3：抓取失败（fetcher 返回 None）不入缓存；"确无 QFII"（[]）入缓存。
    披露窗口内的空结果按 EMPTY_RESULT_TTL_DAYS 过期，过期后下次调用会重试。
    """
    today = today or date.today()
    target_dates = _recent_quarter_dates(quarters, today=today)
    cache = _read_cache(symbol)
    dirty = False
    out: dict[str, list[dict]] = {}
    for d in target_dates:
        entry = cache.get(d)
        if entry is not None and _is_entry_fresh(entry, d, today):
            data = _entry_data(entry)
            if data is not None:
                out[d] = data
                continue
        fetched = fetcher(symbol, d)
        if fetched is None:
            continue
        cache[d] = {"data": fetched, "cached_at": today.isoformat()}
        out[d] = fetched
        dirty = True
    if dirty:
        try:
            _write_cache(symbol, cache)
        except Exception as e:
            logger.warning("QFII 缓存写入失败 %s: %s", symbol, e)
    return out
