"""
基本面数据同步与计算 — 长期分析师团数据基础

主要接口：
  • sync_industry(db)                — 回填 Stock.industry
  • sync_financial_metrics(symbol, db, years=5) — 同步财报到 FinancialMetric
  • sync_disclosure_dates(db, years=3)          — 批量回填 FinancialMetric.disclosure_date
  • compute_piotroski_factors(symbol, db)       — 9 因子 F-Score
  • compute_jingqi_deltas(symbol, db, peers=None) — Δ 类指标 + 行业分位
  • compute_roe(net_profit, total_equity)       — 内部 helper

akshare 接口策略：
  • stock_individual_info_em(symbol)            — 行业信息（每股 1 次）
  • stock_financial_abstract(symbol)            — 66 期财务摘要（每股 1 次）
  • stock_financial_analysis_indicator(symbol)  — ROE/资产周转率等衍生指标（每股 1 次）
  • stock_report_disclosure(market, period)     — 巨潮预约披露，按期次批量拉全市场披露日

所有同步均幂等：按 (symbol, report_date) 唯一约束跳过已存在记录。
"""
from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import pandas as pd

from backend.data.database import FinancialMetric, HolderSnapshot, Stock

logger = logging.getLogger(__name__)


def _akshare_retry(max_attempts: int = 3, delay: float = 1.5):
    """AkShare 网络调用指数退避重试"""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        logger.warning("%s 最终失败: %s", fn.__name__, e)
                        return pd.DataFrame()
                    wait = delay * (2 ** attempt)
                    logger.warning("%s 失败（第%d次），%.1fs后重试: %s",
                                   fn.__name__, attempt + 1, wait, e)
                    time.sleep(wait)
        return wrapper
    return decorator


# ── 工具 ──────────────────────────────────────────────────────────────

def _safe_float(v) -> float | None:
    """把 akshare 返回的字符串/带百分号/带"亿"的数值统一转 float，无法转返回 None"""
    if v is None or pd.isna(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s in ("--", "-", "nan", "None"):
        return None
    s = s.replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def _pick(row: pd.Series, *keys: str) -> Any:
    """从 row 中取第一个存在的列（兼容 akshare 字段重命名）"""
    for k in keys:
        if k in row.index:
            v = row[k]
            if pd.notna(v):
                return v
    return None


def compute_roe(net_profit: float | None, total_equity: float | None) -> float | None:
    """ROE = 净利润 / 平均股东权益（用期末权益近似），返回百分数"""
    if net_profit is None or total_equity is None or total_equity == 0:
        return None
    return round(net_profit / total_equity * 100, 4)


def compute_asset_turnover(revenue: float | None, total_assets: float | None) -> float | None:
    """资产周转率 = 营业收入 / 总资产"""
    if revenue is None or total_assets is None or total_assets == 0:
        return None
    return round(revenue / total_assets, 4)


# ── 行业回填 ──────────────────────────────────────────────────────────

def sync_industry(db) -> int:
    """
    给所有 active CN 股回填 Stock.industry。返回更新条数。
    幂等：industry 已有值的不再覆盖。
    """
    try:
        import akshare as ak
    except ImportError:
        logger.error("akshare 未安装")
        return 0

    stocks = db.query(Stock).filter(Stock.active, Stock.market == "CN").all()
    updated = 0
    for s in stocks:
        if s.industry:
            continue
        try:
            df = ak.stock_individual_info_em(symbol=s.symbol)
            # 返回 DataFrame，列为 item / value
            ind = None
            for _, row in df.iterrows():
                item = str(row.get("item", ""))
                if "行业" in item:
                    ind = str(row.get("value", "")).strip()
                    break
            if ind:
                s.industry = ind
                updated += 1
                logger.info("industry %s -> %s", s.symbol, ind)
            time.sleep(0.3)  # 礼貌限速
        except Exception as e:
            logger.warning("sync_industry %s 失败: %s", s.symbol, e)
    db.commit()
    return updated


# ── 财报同步 ──────────────────────────────────────────────────────────

@_akshare_retry(max_attempts=3, delay=1.5)
def _fetch_abstract(ak, symbol: str) -> pd.DataFrame:
    """财务摘要（含历史多期，列 = 报告期，行 = 指标）"""
    return ak.stock_financial_abstract(symbol=symbol)


@_akshare_retry(max_attempts=3, delay=1.5)
def _fetch_indicator(ak, symbol: str, years: int = 5) -> pd.DataFrame:
    """财务指标（含 ROE、资产周转率等衍生指标）。必须传 start_year 否则返回空。"""
    start_year = str(datetime.now().year - years)
    return ak.stock_financial_analysis_indicator(symbol=symbol, start_year=start_year)


def _row_lookup(df: pd.DataFrame, *needles: str) -> pd.Series | None:
    """
    在指标列模糊匹配指标名，返回该行。
    优先精确匹配名为 '指标' 的列（akshare 财务摘要的实际指标名列）；
    退而求其次匹配 '项目'，最后才匹配 '选项'（它的值是"常用指标/每股指标"分类标签，不是指标名）。
    """
    if df.empty:
        return None
    label_col = None
    for exact in ("指标", "项目"):
        if exact in df.columns:
            label_col = exact
            break
    if label_col is None:
        for c in df.columns:
            if "指标" in str(c) or "项目" in str(c):
                label_col = c
                break
    if label_col is None:
        return None
    for needle in needles:
        mask = df[label_col].astype(str).str.contains(needle, na=False)
        if mask.any():
            return df[mask].iloc[0]
    return None


def sync_financial_metrics(symbol: str, db, years: int = 5) -> int:
    """
    同步单股 financial_metrics 表。返回新增行数。

    策略：
      1. 一次性拉财务摘要 + 财务指标
      2. 摘要列名是报告期 (如 '20240930')，解析最近 years*4 期
      3. 摘要按行索引常用指标：归母净利润、营业总收入、毛利率、销售净利率
      4. 财务指标提供 ROE、资产周转率、流动比率 等衍生指标
      5. 同比由相邻同期数据 (前 4 个报告期前) 计算
      6. 幂等写入 FinancialMetric
    """
    try:
        import akshare as ak
    except ImportError:
        return 0

    abs_df = _fetch_abstract(ak, symbol)
    if abs_df.empty:
        return 0

    # 财务摘要的列形如: ['选项', '20240930', '20240630', '20240331', ...] (字符串日期)
    date_cols = [c for c in abs_df.columns if str(c).isdigit() and len(str(c)) == 8]
    date_cols = sorted(date_cols, reverse=True)[: years * 4]
    if not date_cols:
        logger.warning("无报告期列: %s", symbol)
        return 0

    # 提取指标行
    revenue_row = _row_lookup(abs_df, "营业总收入", "营业收入")
    net_profit_row = _row_lookup(abs_df, "归母净利润", "净利润")
    gross_margin_row = _row_lookup(abs_df, "毛利率", "销售毛利率")

    # 财务指标（必须传 years 才能拿到 stock_financial_analysis_indicator 数据）
    ind_df = _fetch_indicator(ak, symbol, years=years)
    ind_by_date: dict[str, dict[str, float | None]] = {}
    if not ind_df.empty:
        date_col = next((c for c in ind_df.columns if "日期" in str(c)), None)
        if date_col:
            for _, r in ind_df.iterrows():
                # 日期可能是 datetime.date 或 字符串 'YYYY-MM-DD'
                d = str(r[date_col]).replace("-", "")[:8]
                # 衍生计算：从 资产负债率% 和 总资产 反推 long_term_debt（用长期负债比率%）
                total_assets = _safe_float(_pick(r, "总资产(元)", "资产总计", "总资产"))
                lt_debt_ratio = _safe_float(_pick(r, "长期负债比率(%)", "长期负债比率"))
                long_term_debt = (total_assets * lt_debt_ratio / 100
                                  if (total_assets and lt_debt_ratio is not None) else None)
                # equity 从 股东权益比率% 反推
                equity_ratio = _safe_float(_pick(r, "股东权益比率(%)", "股东权益比率"))
                total_equity = (total_assets * equity_ratio / 100
                                if (total_assets and equity_ratio is not None) else None)
                # operating_cf 从 经营现金净流量对销售收入比率(%) 反推 — 需 revenue，留 None 由摘要补
                ind_by_date[d] = {
                    "roe": _safe_float(_pick(r, "净资产收益率(%)", "加权净资产收益率(%)", "净资产报酬率(%)")),
                    "asset_turnover": _safe_float(_pick(r, "总资产周转率(次)", "总资产周转率")),
                    "total_assets": total_assets,
                    "total_equity": total_equity,
                    "long_term_debt": long_term_debt,
                    "current_ratio": _safe_float(_pick(r, "流动比率", "流动比率(倍)")),
                    "operating_cf_ratio": _safe_float(_pick(r, "经营现金净流量对销售收入比率(%)")),
                    "shares_outstanding": None,  # 该接口不含，留空
                }

    # 构造每期的 metric dict
    inserted = 0
    rows_by_date: dict[str, dict] = {}
    for d in date_cols:
        report_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        period_type = {
            "0331": "Q1", "0630": "Q2", "0930": "Q3", "1231": "Annual",
        }.get(d[4:], "Q?")

        rev = _safe_float(revenue_row[d]) if revenue_row is not None and d in revenue_row.index else None
        np_ = _safe_float(net_profit_row[d]) if net_profit_row is not None and d in net_profit_row.index else None
        gm = _safe_float(gross_margin_row[d]) if gross_margin_row is not None and d in gross_margin_row.index else None

        ind = ind_by_date.get(d, {})

        # operating_cf 从 ratio 推算：cfo = ratio% × revenue / 100
        ocf_ratio = ind.get("operating_cf_ratio") if ind else None
        operating_cf = (ocf_ratio * rev / 100) if (ocf_ratio is not None and rev) else None

        rows_by_date[d] = {
            "report_date": report_date,
            "period_type": period_type,
            "revenue": rev,
            "net_profit": np_,
            "gross_margin": gm,
            "roe": ind.get("roe"),
            "asset_turnover": ind.get("asset_turnover"),
            "total_assets": ind.get("total_assets"),
            "total_equity": ind.get("total_equity"),
            "long_term_debt": ind.get("long_term_debt"),
            "current_ratio": ind.get("current_ratio"),
            "operating_cf": operating_cf,
            "shares_outstanding": ind.get("shares_outstanding"),
        }

    # 同比计算：取 4 期前的同月数据对比
    sorted_dates = sorted(rows_by_date.keys(), reverse=True)
    for d in sorted_dates:
        r = rows_by_date[d]
        prev_year_d = f"{int(d[:4])-1}{d[4:]}"
        prev = rows_by_date.get(prev_year_d)
        if prev:
            if r["revenue"] and prev["revenue"]:
                r["revenue_yoy"] = round((r["revenue"] / prev["revenue"] - 1) * 100, 2)
            if r["net_profit"] is not None and prev["net_profit"]:
                r["net_profit_yoy"] = round((r["net_profit"] / prev["net_profit"] - 1) * 100, 2)
        # 若 ROE/资产周转率 在指标接口缺失，则现场计算
        if r.get("roe") is None:
            r["roe"] = compute_roe(r.get("net_profit"), r.get("total_equity"))
        if r.get("asset_turnover") is None:
            r["asset_turnover"] = compute_asset_turnover(r.get("revenue"), r.get("total_assets"))

    # 写库（幂等）
    for r in rows_by_date.values():
        exists = db.query(FinancialMetric.id).filter(
            FinancialMetric.symbol == symbol,
            FinancialMetric.report_date == r["report_date"],
        ).first()
        if exists:
            continue
        db.add(FinancialMetric(
            symbol=symbol,
            report_date=r["report_date"],
            period_type=r["period_type"],
            revenue=r.get("revenue"),
            revenue_yoy=r.get("revenue_yoy"),
            net_profit=r.get("net_profit"),
            net_profit_yoy=r.get("net_profit_yoy"),
            total_assets=r.get("total_assets"),
            total_equity=r.get("total_equity"),
            long_term_debt=r.get("long_term_debt"),
            current_ratio=r.get("current_ratio"),
            operating_cf=r.get("operating_cf"),
            shares_outstanding=r.get("shares_outstanding"),
            gross_margin=r.get("gross_margin"),
            roe=r.get("roe"),
            asset_turnover=r.get("asset_turnover"),
            raw_json=json.dumps({k: v for k, v in r.items() if v is not None}, ensure_ascii=False),
        ))
        inserted += 1
    db.commit()
    return inserted


# ── Piotroski F-Score（9 因子） ───────────────────────────────────────

PIOTROSKI_FACTORS = [
    "roa_positive", "cfo_positive", "roa_improving", "cfo_gt_ni",
    "leverage_decreasing", "current_ratio_improving", "no_new_shares",
    "gross_margin_improving", "asset_turnover_improving",
]


def _roa(metric: FinancialMetric) -> float | None:
    """Compute return on assets from a FinancialMetric row."""
    if metric.net_profit is None or not metric.total_assets:
        return None
    return metric.net_profit / metric.total_assets


def _parse_report_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.strptime(value[:10], "%Y-%m-%d")


def _add_months(value: datetime, months: int) -> datetime:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    days_in_month = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return value.replace(year=year, month=month, day=min(value.day, days_in_month[month - 1]))


def _no_new_shares_from_holders(symbol: str, as_of: datetime, db) -> bool | None:
    latest = (
        db.query(HolderSnapshot)
        .filter(
            HolderSnapshot.symbol == symbol,
            HolderSnapshot.report_date <= as_of,
            HolderSnapshot.total_shares.isnot(None),
        )
        .order_by(HolderSnapshot.report_date.desc())
        .first()
    )
    if latest is None:
        return None

    window_start = _add_months(as_of, -15)
    window_end = _add_months(as_of, -9)
    target = _add_months(as_of, -12)
    candidates = (
        db.query(HolderSnapshot)
        .filter(
            HolderSnapshot.symbol == symbol,
            HolderSnapshot.report_date >= window_start,
            HolderSnapshot.report_date <= window_end,
            HolderSnapshot.total_shares.isnot(None),
        )
        .all()
    )
    if not candidates:
        return None

    earlier = min(candidates, key=lambda row: abs((row.report_date - target).total_seconds()))
    return bool(latest.total_shares <= earlier.total_shares * 1.02)


def compute_piotroski_factors(symbol: str, db) -> dict:
    """
    9 因子 F-Score（盈利能力 4 + 杠杆流动性 3 + 经营效率 2）

    Returns:
        {
          "score": int,
          "score_denominator": int,
          "factors": {factor_name: bool | None},
          "report_period": "2024-Q3",
          "comparison_period": "2023-Q3",
          "available": bool,
        }
    """
    rows = (db.query(FinancialMetric)
              .filter(FinancialMetric.symbol == symbol)
              .order_by(FinancialMetric.report_date.desc())
              .limit(8).all())
    if len(rows) < 2:
        return {"score": 0, "factors": {}, "report_period": None,
                "comparison_period": None, "available": False,
                "reason": "数据不足"}

    cur = rows[0]
    # 找去年同期（report_date 月份相同）
    cur_month = cur.report_date[5:]   # "09-30"
    prev = next((r for r in rows[1:] if r.report_date[5:] == cur_month), None)
    if prev is None:
        prev = rows[1]   # fallback 最近一期

    f: dict[str, bool | None] = {}
    # 盈利能力
    roa_cur = _roa(cur)
    roa_prev = _roa(prev)
    f["roa_positive"] = roa_cur is not None and roa_cur > 0
    f["cfo_positive"] = cur.operating_cf is not None and cur.operating_cf > 0
    f["roa_improving"] = (roa_cur is not None and roa_prev is not None
                          and roa_cur > roa_prev)
    f["cfo_gt_ni"] = (cur.operating_cf is not None and cur.net_profit is not None
                      and cur.operating_cf > cur.net_profit)

    # 杠杆 / 流动性
    if cur.total_assets and cur.long_term_debt is not None \
       and prev.total_assets and prev.long_term_debt is not None:
        lev_cur = cur.long_term_debt / cur.total_assets
        lev_prev = prev.long_term_debt / prev.total_assets
        f["leverage_decreasing"] = lev_cur < lev_prev
    else:
        f["leverage_decreasing"] = False

    f["current_ratio_improving"] = (cur.current_ratio is not None
                                    and prev.current_ratio is not None
                                    and cur.current_ratio > prev.current_ratio)
    f["no_new_shares"] = _no_new_shares_from_holders(symbol, _parse_report_datetime(cur.report_date), db)

    # 经营效率
    f["gross_margin_improving"] = (cur.gross_margin is not None
                                   and prev.gross_margin is not None
                                   and cur.gross_margin > prev.gross_margin)
    f["asset_turnover_improving"] = (cur.asset_turnover is not None
                                     and prev.asset_turnover is not None
                                     and cur.asset_turnover > prev.asset_turnover)

    score = sum(1 for v in f.values() if v is True)
    score_denominator = sum(1 for v in f.values() if v is not None)
    return {
        "score": score,
        "score_denominator": score_denominator,
        "factors": f,
        "report_period": cur.report_date,
        "comparison_period": prev.report_date,
        "available": True,
        "raw": {
            "roa_cur": roa_cur, "roa_prev": roa_prev,
            "cfo_cur": cur.operating_cf, "ni_cur": cur.net_profit,
            "gm_cur": cur.gross_margin, "gm_prev": prev.gross_margin,
        },
    }


# ── 景气投资 jingqi（Δ 类指标 + 行业分位） ───────────────────────────

def compute_jingqi_deltas(symbol: str, db, peers: Iterable[str] | None = None) -> dict:
    """
    Δ 类指标 + 同行业分位（开源证券 7×34 框架核心）

    transitions:
      • profit_negative_to_positive: 上期 Δ 利润增速 < 0 且当期 > 0
      • revenue_negative_to_positive: 同上，收入
    """
    rows = (db.query(FinancialMetric)
              .filter(FinancialMetric.symbol == symbol)
              .order_by(FinancialMetric.report_date.desc())
              .limit(8).all())
    if len(rows) < 2:
        return {"available": False, "reason": "数据不足"}

    cur, prev = rows[0], rows[1]

    def _delta(field) -> float | None:
        """Compute period-over-period delta for a metric field."""
        v_cur = getattr(cur, field)
        v_prev = getattr(prev, field)
        if v_cur is None or v_prev is None:
            return None
        return round(v_cur - v_prev, 2)

    delta_np_yoy = _delta("net_profit_yoy")
    delta_rev_yoy = _delta("revenue_yoy")
    delta_roe = _delta("roe")

    # 转折信号
    prev2 = rows[2] if len(rows) >= 3 else None
    transitions = {"profit_negative_to_positive": False,
                   "revenue_negative_to_positive": False}
    if prev2 and cur.net_profit_yoy is not None and prev.net_profit_yoy is not None and prev2.net_profit_yoy is not None:
        prev_delta = prev.net_profit_yoy - prev2.net_profit_yoy
        cur_delta = cur.net_profit_yoy - prev.net_profit_yoy
        transitions["profit_negative_to_positive"] = (prev_delta < 0 and cur_delta > 0)
    if prev2 and cur.revenue_yoy is not None and prev.revenue_yoy is not None and prev2.revenue_yoy is not None:
        prev_delta = prev.revenue_yoy - prev2.revenue_yoy
        cur_delta = cur.revenue_yoy - prev.revenue_yoy
        transitions["revenue_negative_to_positive"] = (prev_delta < 0 and cur_delta > 0)

    # 同行业分位
    industry_pctile: dict[str, float | None] = {
        "delta_net_profit_yoy": None,
        "delta_revenue_yoy": None,
        "delta_roe": None,
    }
    if peers:
        peer_deltas: dict[str, list[float]] = {
            "delta_net_profit_yoy": [],
            "delta_revenue_yoy": [],
            "delta_roe": [],
        }
        for psym in peers:
            if psym == symbol:
                continue
            prows = (db.query(FinancialMetric)
                       .filter(FinancialMetric.symbol == psym)
                       .order_by(FinancialMetric.report_date.desc())
                       .limit(2).all())
            if len(prows) < 2:
                continue
            for k, f in [("delta_net_profit_yoy", "net_profit_yoy"),
                         ("delta_revenue_yoy", "revenue_yoy"),
                         ("delta_roe", "roe")]:
                vc, vp = getattr(prows[0], f), getattr(prows[1], f)
                if vc is not None and vp is not None:
                    peer_deltas[k].append(vc - vp)

        def _pctile(value, arr) -> float | None:
            """Return the fraction of arr values strictly below value."""
            if value is None or not arr:
                return None
            below = sum(1 for x in arr if x < value)
            return round(below / len(arr), 3)

        industry_pctile["delta_net_profit_yoy"] = _pctile(delta_np_yoy, peer_deltas["delta_net_profit_yoy"])
        industry_pctile["delta_revenue_yoy"] = _pctile(delta_rev_yoy, peer_deltas["delta_revenue_yoy"])
        industry_pctile["delta_roe"] = _pctile(delta_roe, peer_deltas["delta_roe"])

    return {
        "available": True,
        "delta_net_profit_yoy": delta_np_yoy,
        "delta_revenue_yoy": delta_rev_yoy,
        "delta_roe": delta_roe,
        "industry_pctile": industry_pctile,
        "transitions": transitions,
        "report_period": cur.report_date,
        "raw": {
            "net_profit_yoy_cur": cur.net_profit_yoy,
            "net_profit_yoy_prev": prev.net_profit_yoy,
            "revenue_yoy_cur": cur.revenue_yoy,
            "revenue_yoy_prev": prev.revenue_yoy,
            "roe_cur": cur.roe,
            "roe_prev": prev.roe,
        },
    }


# ── 披露日批量回填 ────────────────────────────────────────────────────

# akshare stock_report_disclosure 接受的 period 后缀 → report_date 月日
# 注意：akshare 用"一季"/"三季"（不带"报"），"半年报"/"年报"（带"报"）
_PERIOD_SUFFIX: dict[str, str] = {
    "年报":  "12-31",
    "三季":  "09-30",
    "半年报": "06-30",
    "一季":  "03-31",
}


def _period_to_report_date(year: int, period_name: str) -> str | None:
    suffix = _PERIOD_SUFFIX.get(period_name)
    if suffix is None:
        return None
    return f"{year}-{suffix}"


def sync_disclosure_dates(db, years: int = 3) -> int:
    """
    批量回填 FinancialMetric.disclosure_date。

    调用巨潮 stock_report_disclosure（全市场，按期次），将"实际披露"日期写入
    已存在的 FinancialMetric 行。优先用"实际披露"，若为空则用"首次预约"（预计日期）。

    返回更新条数。
    """
    try:
        import akshare as ak
    except ImportError:
        logger.error("akshare 未安装")
        return 0

    current_year = datetime.now().year
    updated = 0

    for year in range(current_year - years + 1, current_year + 1):
        for period_name in ("年报", "三季", "半年报", "一季"):
            period_str = f"{year}{period_name}"
            report_date = _period_to_report_date(year, period_name)
            if report_date is None:
                continue

            try:
                df = ak.stock_report_disclosure(market="沪深京", period=period_str)
                time.sleep(0.5)
            except Exception as e:
                logger.warning("stock_report_disclosure %s 失败: %s", period_str, e)
                continue

            if df.empty or "股票代码" not in df.columns:
                continue

            for _, row in df.iterrows():
                symbol = str(row.get("股票代码", "")).strip().zfill(6)
                if not symbol:
                    continue

                # 优先实际披露，回退首次预约
                actual = row.get("实际披露")
                scheduled = row.get("首次预约")
                date_val = actual if pd.notna(actual) else (scheduled if pd.notna(scheduled) else None)
                if date_val is None:
                    continue

                try:
                    disclosure_str = pd.Timestamp(date_val).strftime("%Y-%m-%d")
                except Exception:
                    continue

                rows_updated = (
                    db.query(FinancialMetric)
                    .filter(
                        FinancialMetric.symbol == symbol,
                        FinancialMetric.report_date == report_date,
                    )
                    .update({"disclosure_date": disclosure_str}, synchronize_session=False)
                )
                updated += rows_updated

    db.commit()
    logger.info("sync_disclosure_dates: %d rows updated", updated)
    return updated


def list_peers(symbol: str, db, industry: str | None = None) -> list[str]:
    """同行业自选股列表（首批用自选股池，二期可扩到全市场）"""
    if industry is None:
        s = db.query(Stock).filter(Stock.symbol == symbol).first()
        if s is None or not s.industry:
            return []
        industry = s.industry
    return [r.symbol for r in db.query(Stock).filter(
        Stock.active, Stock.industry == industry
    ).all() if r.symbol != symbol]
