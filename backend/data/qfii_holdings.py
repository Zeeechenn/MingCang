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
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".stock-sage" / "qfii_cache"

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


def _fetch_single_quarter(symbol: str, report_date: str) -> list[dict]:
    """拉单季 QFII 持仓，失败返回 []。仅过滤 QFII 关键词命中的股东。"""
    try:
        import akshare as ak
        df = ak.stock_gdfx_free_top_10_em(symbol=_market_prefix(symbol), date=report_date)
    except Exception as e:
        logger.debug("AkShare 拉取失败 %s %s: %s", symbol, report_date, e)
        return []
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


def _read_cache(symbol: str) -> dict[str, list[dict]]:
    """Read cached QFII holdings for a symbol, returning empty dict on miss."""
    p = _cache_path(symbol)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(symbol: str, data: dict[str, list[dict]]) -> None:
    """Write QFII holdings data to the cache file for a symbol."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(symbol).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_qfii_history(symbol: str, quarters: int = 4,
                     today: date | None = None,
                     fetcher=_fetch_single_quarter) -> dict[str, list[dict]]:
    """
    获取近 quarters 个季度的 QFII 持仓快照。

    返回 {"20251231": [{"holder": "高盛集团", "shares": 1234567, "change": -200000}, ...], ...}
    报告期键按时间倒序（最近季度在前）。

    fetcher 参数用于测试时注入 mock。
    """
    target_dates = _recent_quarter_dates(quarters, today=today)
    cache = _read_cache(symbol)
    dirty = False
    out: dict[str, list[dict]] = {}
    for d in target_dates:
        if d in cache:
            out[d] = cache[d]
            continue
        fetched = fetcher(symbol, d)
        cache[d] = fetched
        out[d] = fetched
        dirty = True
    if dirty:
        try:
            _write_cache(symbol, cache)
        except Exception as e:
            logger.warning("QFII 缓存写入失败 %s: %s", symbol, e)
    return out
