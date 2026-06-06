"""
一次性脚本：批量回填新股票 + 跑完整 LongTermTeam 四路分析

目标股票池：
- 电力：长江电力/国电电力/华能国际/华电国际/中国核电/三峡能源/国电南瑞
- AI半导体：北方华创/寒武纪/海光信息/紫光国微/科大讯飞/海康威视
"""
from __future__ import annotations

import logging
import time

from backend.agents.long_term.storage import save_label
from backend.agents.long_term.team import LongTermTeam
from backend.data.database import SessionLocal, Stock
from backend.data.fundamentals import (
    sync_disclosure_dates,
    sync_financial_metrics,
    sync_industry,
)
from backend.data.market import backfill_if_needed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# (symbol, name, market)
TARGETS = [
    # 电力
    ("600900", "长江电力", "CN"),
    ("600795", "国电电力", "CN"),
    ("600011", "华能国际", "CN"),
    ("600027", "华电国际", "CN"),
    ("601985", "中国核电", "CN"),
    ("600905", "三峡能源", "CN"),
    ("600406", "国电南瑞", "CN"),
    # AI / 半导体
    ("002371", "北方华创", "CN"),
    ("688256", "寒武纪", "CN"),
    ("688041", "海光信息", "CN"),
    ("002049", "紫光国微", "CN"),
    ("002230", "科大讯飞", "CN"),
    ("002415", "海康威视", "CN"),
]


def upsert_stock(db, symbol: str, name: str, market: str) -> Stock:
    s = db.query(Stock).filter(Stock.symbol == symbol).first()
    if s is None:
        s = Stock(symbol=symbol, name=name, market=market, active=True)
        db.add(s)
        db.commit()
        logger.info(f"+ stock added: {symbol} {name}")
    elif not s.active:
        s.active = True
        db.commit()
        logger.info(f"~ stock reactivated: {symbol} {name}")
    return s


def main() -> None:
    db = SessionLocal()
    try:
        # 1) Upsert stocks
        for sym, name, mkt in TARGETS:
            upsert_stock(db, sym, name, mkt)

        # 2) sync industry (覆盖所有 active CN 股)
        try:
            n = sync_industry(db)
            logger.info(f"industry synced: {n} updated")
        except Exception as e:
            logger.warning(f"sync_industry failed: {e}")

        # 3) prices + financial_metrics + disclosure_dates
        for sym, name, mkt in TARGETS:
            try:
                rows = backfill_if_needed(sym, mkt, db, years=5)
                logger.info(f"prices {sym} {name}: +{rows}")
            except Exception as e:
                logger.error(f"prices {sym} failed: {e}")
            time.sleep(0.3)

            try:
                inserted = sync_financial_metrics(sym, db, years=5)
                logger.info(f"financials {sym}: +{inserted}")
            except Exception as e:
                logger.error(f"financials {sym} failed: {e}")
            time.sleep(0.3)

        try:
            n = sync_disclosure_dates(db, years=5)
            logger.info(f"disclosure dates: +{n}")
        except Exception as e:
            logger.warning(f"disclosure dates failed: {e}")

        # 4) Run LongTermTeam
        team = LongTermTeam()
        results = []
        for sym, name, _mkt in TARGETS:
            try:
                label = team.run(sym, name, db)
                save_label(label, db)
                results.append(label)
                logger.info(
                    f">> {sym} {name}: {label.label} score={label.score:.1f} votes={label.votes}"
                )
            except Exception as e:
                logger.error(f"LongTermTeam {sym} failed: {e}")

        # 5) Final summary
        print("\n" + "=" * 70)
        print("FINAL RESULTS")
        print("=" * 70)
        for r in sorted(results, key=lambda x: -x.score):
            print(f"{r.symbol}  {r.label:6s}  score={r.score:+6.1f}  votes={r.votes}")
            for f in r.key_findings[:5]:
                print(f"    - {f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
