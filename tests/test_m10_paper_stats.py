from pathlib import Path


def test_paper_trading_stats_parse_positions_and_compute_summary(tmp_path: Path):
    from paper_trading.stats import compute_summary, parse_positions_table

    doc = """
## 持仓记录

| 股票 | 买入日 | 买入价 | 止损价 | 止盈价 | 状态 | 平仓日 | 平仓价 | 盈亏% |
|------|--------|--------|--------|--------|------|--------|--------|-------|
| 300308 中际旭创 | 2026-05-13 | 100.00 | 90.00 | 120.00 | 已止损 | 2026-05-19 | 90.00 | -10.00% |
| 603986 兆易创新 | 2026-05-13 | 200.00 | 180.00 | 260.00 | 持有中 | — | — | +12.50%（05-20收盘） |
"""
    path = tmp_path / "test.md"
    path.write_text(doc, encoding="utf-8")

    positions = parse_positions_table(path)
    summary = compute_summary(positions)

    assert len(positions) == 2
    assert summary["total_positions"] == 2
    assert summary["closed_positions"] == 1
    assert summary["open_positions"] == 1
    assert summary["realized_win_rate_pct"] == 0.0
    assert summary["realized_return_pct"] == -10.0
    assert summary["open_return_pct"] == 12.5
