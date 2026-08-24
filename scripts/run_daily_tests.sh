#!/usr/bin/env bash
# 明仓「跑测试」每日流水线（SOP 的可执行版本）。
#
# 为什么存在：这 9 步是确定性的固定序列，却一直靠 LLM 子代理在中间维持轮询等待
# ——而 Bash 单次调用上限 10 分钟、作业要跑 20-40 分钟，于是必须后台+轮询，
# 结构上要求代理有"耐心"，而耐心不是模型能可靠提供的（sonnet 连续两轮在此出错）。
# 把序列固化成脚本后：调用方只需在后台起它一次，由 harness 负责等完成通知，
# 没有任何一方需要维持等待循环；同时 --no-shadow / --no-llm / 不带 --force /
# 标签先于深评 这些额度纪律被写死，谁也忘不掉。
#
# 用法：bash scripts/run_daily_tests.sh [YYYY-MM-DD]
#   不传日期 = 今天。收盘后跑（数据必须已定盘）。
set -uo pipefail

REPO="/Users/zeeechenn/mingcang"
cd "$REPO" || exit 1
PY="$REPO/.venv/bin/python3"
DAY="${1:-$(date +%F)}"
STAMP="${DAY//-/}"
SUMMARY="$REPO/paper_trading/_run_summary_${STAMP}.md"

export PYTHONPATH=.
export LOCAL_CLI_PREFER_CODEX=false
export LOCAL_CLI_NO_CODEX_FALLBACK=true

say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$SUMMARY"; }
fail() { say "⛔ 中止：$*"; say "PIPELINE_ABORTED"; exit 1; }

# 额度熔断哨兵：任何一步日志出现即立刻停手（重跑只会在恢复瞬间再打空一次）
quota_check() {
  if grep -q "LLM_QUOTA_EXHAUSTED\|额度耗尽" "$1" 2>/dev/null; then
    fail "$2 触发 LLM 额度熔断，后续步骤全部跳过，不要重跑，等额度恢复"
  fi
}
# 每个作业退出时会打 LLM_CALL_TOTAL，汇总它便于事后核账
calls_of() { grep -o "LLM_CALL_TOTAL claude 调用 [0-9]*" "$1" 2>/dev/null | grep -o "[0-9]*" | tail -1; }

: > "$SUMMARY"
say "=== 明仓跑测试 $DAY ==="

# ── 第 1-3 步：锁 One Loop 20 日门（合计 0 次 LLM 调用，最优先）──────────────
L1="paper_trading/_test2_${STAMP}.log"
say "① test2 官方批次（25 支，--no-shadow）"
"$PY" paper_trading/test2_signal_runner.py --no-shadow > "$L1" 2>&1
quota_check "$L1" "①"
grep -q "产信号 25 · 跳过 0 · 失败 0" "$L1" || fail "① 未达 25/25，见 $L1"
# 数据日必须等于目标日，否则整轮作废（跑早了/抓到旧 bar）
grep -q "data_date==${DAY}" "$L1" || fail "① 数据日不是 ${DAY}（可能未收盘或行情缺失），见 $L1"
say "   ✅ 25/25，data_date==${DAY}"

L2="paper_trading/_m63_postmarket_${STAMP}.log"
say "② One Loop 盘后面板（--no-llm，0 次调用）"
"$PY" -m backend.tools.m63_daily --mode postmarket --date "$DAY" --no-llm > "$L2" 2>&1
grep -q "postmarket_${DAY}.md" "$L2" || fail "② 面板未落盘，见 $L2"
say "   ✅ 面板已写"

say "③ One Loop 审计"
SNAP="/tmp/audit_${STAMP}.db"; cp mingcang.db "$SNAP"
"$PY" scripts/audit_one_loop_continuity.py --db "$SNAP" --implementation-since 2026-08-19 2>&1 \
  | "$PY" -c "
import json,sys
d=json.load(sys.stdin)
for x in d['days']: print(f\"   {x['date']} -> {x['status']} {x['blockers']}\")
m=d['metrics']
print(f\"   close_confirmed_days={m['close_confirmed_days']} → 20 日门 {m['close_confirmed_days']}/20\")
today=[x for x in d['days'] if x['date']=='${DAY}']
print('   ⛔ 今日未 complete，门断了' if (today and today[0]['status']!='complete') else '   ✅ 今日 complete，门已锁')
" | tee -a "$SUMMARY"
say "   —— 门已处理完，后续步骤即使失败也不影响 20 日门 ——"

# ── 第 4-8 步：实盘决策线（可断可补）─────────────────────────────────────
L4="live_trading/_live_broad_${STAMP}.log"
say "④ 实盘广筛（56 支，--no-multi-agent --no-shadow）"
"$PY" paper_trading/test2_signal_runner.py --universe live_trading/live_universe.json \
  --no-multi-agent --no-shadow > "$L4" 2>&1
quota_check "$L4" "④"
say "   $(grep -o '股票池 .* 陈旧剔除 [0-9]*' "$L4" | tail -1)"

say "⑤ 漏斗"
SUB="live_trading/_live_subset_${DAY}.json"
"$PY" live_trading/live_subset.py "$DAY" 2>&1 | tee -a "$SUMMARY"
[ -f "$SUB" ] || fail "⑤ 子集未生成"

SYMS=$("$PY" -c "import json;print(','.join(s['symbol'] for s in json.load(open('$SUB'))['stocks']))")
[ -n "$SYMS" ] || fail "⑤ 子集为空"

# ⑥ 标签：只刷子集、**绝不带 --force**（有效期 7 天，新鲜的自动跳过）
L6="paper_trading/_longterm_labels_${STAMP}.log"
say "⑥ 长期标签（只刷漏斗子集，不带 --force，fast 档，预算 120）"
LOCAL_CLI_FORCE_FAST_TIER=true LOCAL_CLI_CALL_BUDGET=120 \
  "$PY" paper_trading/build_longterm_labels.py --timeout 300 \
  --universe live_trading/live_universe.json --symbols "$SYMS" > "$L6" 2>&1
quota_check "$L6" "⑥"
say "   $(grep -o '完成：.*' "$L6" | tail -1)  调用 $(calls_of "$L6") 次"

# ⑦ 深评：只跑「标签非规避 ∪ 持仓」——规避是硬闸，深评规避的支纯属白花
DEEP="live_trading/_live_deep_subset_${DAY}.json"
"$PY" - "$SUB" "$DEEP" << 'PYEOF' | tee -a "$SUMMARY"
import json, sqlite3, sys
sub, out = sys.argv[1], sys.argv[2]
stocks = json.load(open(sub))["stocks"]
held = {p["symbol"] for p in json.load(open("live_trading/live_state.json")).get("positions") or []}
c = sqlite3.connect("file:mingcang.db?mode=ro", uri=True)
cols = [r[1] for r in c.execute("PRAGMA table_info(long_term_labels)")]
keep, drop = [], []
for s in stocks:
    r = c.execute("select * from long_term_labels where symbol=? order by rowid desc limit 1", (s["symbol"],)).fetchone()
    lab = dict(zip(cols, r))["label"] if r else None
    if s["symbol"] in held or lab != "规避":
        keep.append(s)
    else:
        drop.append(f'{s["symbol"]}({lab})')
json.dump({"version": "deep", "source": sub, "stocks": keep}, open(out, "w"), ensure_ascii=False, indent=2)
print(f"   ⑦ 深评范围：{len(stocks)} → {len(keep)} 支（规避剔除 {len(drop)}：{' '.join(drop) or '无'}）")
PYEOF

DEEP_N=$("$PY" -c "import json;print(len(json.load(open('$DEEP'))['stocks']))")
L7="live_trading/_live_deep_${STAMP}.log"
if [ "$DEEP_N" -gt 0 ]; then
  say "⑦ 子集深评（$DEEP_N 支，multi-agent）"
  "$PY" paper_trading/test2_signal_runner.py --universe "$DEEP" \
    --multi-agent --no-shadow --workers 4 > "$L7" 2>&1
  quota_check "$L7" "⑦"
  say "   调用 $(calls_of "$L7") 次"
else
  say "⑦ 深评范围为空（全部规避且无持仓）→ 跳过"
fi

L8="paper_trading/_test2_ab_${STAMP}.log"
say "⑧ AB 回放"
"$PY" paper_trading/test2_ab_runner.py --start 2026-07-03 --end "$DAY" > "$L8" 2>&1
say "   $(tail -3 "$L8" | head -2 | tr '\n' ' ')"

# ── 汇总 ────────────────────────────────────────────────────────────────
TOTAL=0
for f in "$L1" "$L4" "$L6" "$L7"; do
  n=$(calls_of "$f"); TOTAL=$((TOTAL + ${n:-0}))
done
say ""
say "=== 本轮 LLM 调用合计 ≈ ${TOTAL} 次（基线 142，目标 ≈95）==="
say "产物：$L1 / $L4 / $L6 / $L7 / $L8 / $SUB / $DEEP"
say "PIPELINE_DONE"
