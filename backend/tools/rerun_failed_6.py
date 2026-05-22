"""
重跑配额超限的 6 只 AI/半导体股，只跑 LongTermTeam，不再回填数据。
"""
import logging

from backend.agents.long_term.storage import save_label
from backend.agents.long_term.team import LongTermTeam
from backend.data.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

TARGETS = [
    ("002371", "北方华创"),
    ("688256", "寒武纪"),
    ("688041", "海光信息"),
    ("002049", "紫光国微"),
    ("002230", "科大讯飞"),
    ("002415", "海康威视"),
]


def main() -> None:
    db = SessionLocal()
    try:
        team = LongTermTeam()
        results = []
        for sym, name in TARGETS:
            try:
                label = team.run(sym, name, db)
                save_label(label, db)
                results.append(label)
                logger.info(
                    f">> {sym} {name}: {label.label} score={label.score:.1f} votes={label.votes}"
                )
            except Exception as e:
                logger.error(f"LongTermTeam {sym} failed: {e}")

        print("\n" + "=" * 70)
        print("FINAL RESULTS (6 AI/semi stocks rerun)")
        print("=" * 70)
        for r in sorted(results, key=lambda x: -x.score):
            print(f"{r.symbol}  {r.label:6s}  score={r.score:+6.1f}  votes={r.votes}")
            for f in r.key_findings:
                print(f"    - {f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
