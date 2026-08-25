#!/usr/bin/env bash
# 明仓「跑测试」每日流水线（SOP 的可执行版本）。
#
# 这 8 步是确定性的固定序列。调用方只需启动脚本一次，由 harness 等待完成；
# 无需让 LLM 子代理维持轮询。--no-shadow、m63 的 --no-llm、标签不带
# --force 且先于深评等额度纪律固定在这里。
#
# 用法：bash scripts/run_daily_tests.sh [YYYY-MM-DD]
#   不传日期 = 今天。收盘后跑（数据必须已定盘）。
set -uo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${MINGCANG_REPO_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
cd "$REPO" || exit 1
PY="${MINGCANG_PYTHON:-$REPO/.venv/bin/python3}"
DAY="${1:-$(date +%F)}"
[[ "$DAY" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
  || { echo "PIPELINE_ABORTED: 日期必须为 YYYY-MM-DD"; exit 2; }
STAMP="${DAY//-/}"
SUMMARY="$REPO/paper_trading/_run_summary_${STAMP}.md"
STATE="$REPO/paper_trading/_run_state_${STAMP}.json"
RUNTIME_ROOT="${MINGCANG_DAILY_RUNTIME_DIR:-${TMPDIR:-/tmp}/mingcang-daily-pipeline}"
LOCK_DIR="$RUNTIME_ROOT/pipeline.lock"
RUN_DIR=""
LOCK_HELD=false
CURRENT_STEP="bootstrap"
ONE_LOOP_STATUS="pending"

export PYTHONPATH=.
export LOCAL_CLI_PREFER_CODEX=false
export LOCAL_CLI_NO_CODEX_FALLBACK=true

say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$SUMMARY"; }
write_state() {
  "$PY" scripts/update_daily_pipeline_state.py \
    --path "$STATE" --date "$DAY" --status "$1" --step "$CURRENT_STEP" \
    --message "$2" --one-loop-status "$ONE_LOOP_STATUS" "${@:3}"
}
fail() {
  local message="$*"
  write_state aborted "$message" >/dev/null 2>&1 || true
  say "⛔ 中止：$message"
  say "PIPELINE_ABORTED"
  exit 1
}
begin_step() {
  CURRENT_STEP="$1"
  write_state running "$2" >/dev/null || fail "无法更新结构化运行状态：$STATE"
}
cleanup() {
  if [ "$LOCK_HELD" = true ]; then
    rm -f "$LOCK_DIR/pid"
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'fail "收到终止信号"' INT TERM

[ -x "$PY" ] || { echo "PIPELINE_ABORTED: Python 不可执行：$PY"; exit 1; }
mkdir -p "$RUNTIME_ROOT" || { echo "PIPELINE_ABORTED: 无法创建运行目录"; exit 1; }
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  owner="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -z "$owner" ]; then
    echo "PIPELINE_ABORTED: 单实例锁正在初始化或损坏，请确认没有运行中的流水线"
    exit 3
  fi
  if [[ "$owner" =~ ^[0-9]+$ ]] && kill -0 "$owner" 2>/dev/null; then
    echo "PIPELINE_ABORTED: 已有每日流水线运行中（pid=${owner}）"
    exit 3
  fi
  rm -f "$LOCK_DIR/pid"
  rmdir "$LOCK_DIR" 2>/dev/null || {
    echo "PIPELINE_ABORTED: 无法清理失效锁 $LOCK_DIR"
    exit 3
  }
  mkdir "$LOCK_DIR" || { echo "PIPELINE_ABORTED: 无法获取单实例锁"; exit 3; }
fi
LOCK_HELD=true
printf '%s\n' "$$" > "$LOCK_DIR/pid" \
  || { echo "PIPELINE_ABORTED: 无法记录单实例锁 owner"; exit 3; }
RUN_DIR="$(mktemp -d "$RUNTIME_ROOT/run-${STAMP}.XXXXXX")" || {
  echo "PIPELINE_ABORTED: 无法创建本轮临时目录"
  exit 1
}

# 额度熔断哨兵：任何一步日志出现即立刻停手（重跑只会在恢复瞬间再打空一次）。
quota_check() {
  if grep -q "LLM_QUOTA_EXHAUSTED\|额度耗尽" "$1" 2>/dev/null; then
    fail "$2 触发 LLM 额度熔断，后续步骤全部跳过，不要重跑，等额度恢复"
  fi
}

# 每个作业退出时会打 LLM_CALL_TOTAL，汇总它便于事后核账。
calls_of() {
  local value
  value=$(grep -o "LLM_CALL_TOTAL claude 调用 [0-9]*" "$1" 2>/dev/null \
    | grep -o "[0-9]*" | tail -1 || true)
  printf '%s' "${value:-0}"
}

run_logged() {
  local log="$1" label="$2" rc
  shift 2
  "$@" > "$log" 2>&1
  rc=$?
  quota_check "$log" "$label"
  [ "$rc" -eq 0 ] || fail "$label 命令失败（exit=${rc}），见 $log"
}

: > "$SUMMARY"
rm -f "$STATE"
say "=== 明仓跑测试 $DAY ==="
write_state running "pipeline started" >/dev/null || fail "无法初始化结构化运行状态：$STATE"

# ── 第 1-3 步：锁 One Loop 20 日门（最优先；仅第 2 步强制 0 LLM）───────────
L1="paper_trading/_test2_${STAMP}.log"
begin_step "01_test2" "test2 official batch"
say "① test2 官方批次（25 支，--no-shadow）"
run_logged "$L1" "①" "$PY" paper_trading/test2_signal_runner.py --no-shadow
grep -q "产信号 25 · 跳过 0 · 失败 0" "$L1" || fail "① 未达 25/25，见 $L1"
grep -q "data_date==${DAY}" "$L1" \
  || fail "① 数据日不是 ${DAY}（可能未收盘或行情缺失），见 $L1"
say "   ✅ 25/25，data_date==${DAY}；本步 LLM 调用 $(calls_of "$L1") 次"

L2="paper_trading/_m63_postmarket_${STAMP}.log"
begin_step "02_postmarket" "One Loop postmarket panel"
say "② One Loop 盘后面板（--no-llm，0 次调用）"
run_logged "$L2" "②" "$PY" -m backend.tools.m63_daily \
  --mode postmarket --date "$DAY" --no-llm
grep -q "postmarket_${DAY}.md" "$L2" || fail "② 面板未落盘，见 $L2"
say "   ✅ 面板已写"

begin_step "03_one_loop" "One Loop continuity audit"
say "③ One Loop 审计"
SNAP="$RUN_DIR/audit.db"
AUDIT_JSON="$RUN_DIR/one_loop.json"
L3_SNAPSHOT="$RUN_DIR/snapshot.log"
L3_AUDIT="$RUN_DIR/one_loop_audit.log"
run_logged "$L3_SNAPSHOT" "③-快照" "$PY" scripts/sqlite_consistent_snapshot.py \
  --source "$REPO/mingcang.db" --destination "$SNAP"
run_logged "$L3_AUDIT" "③-审计" "$PY" scripts/audit_one_loop_continuity.py \
  --db "$SNAP" --implementation-since 2026-08-19 --output "$AUDIT_JSON"
"$PY" - "$AUDIT_JSON" "$DAY" << 'PYEOF' | tee -a "$SUMMARY"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
day = sys.argv[2]
for item in payload["days"]:
    print(f"   {item['date']} -> {item['status']} {item['blockers']}")
metrics = payload["metrics"]
print(
    f"   close_confirmed_days={metrics['close_confirmed_days']} "
    f"→ 20 日门 {metrics['close_confirmed_days']}/20"
)
today = [item for item in payload["days"] if item["date"] == day]
if not today:
    print("   ⛔ 审计结果缺少目标日")
    raise SystemExit(3)
if today[0]["status"] != "complete":
    print(f"   ⛔ 今日未 complete：{today[0]['blockers']}")
    raise SystemExit(4)
print("   ✅ 今日 complete，门已锁")
PYEOF
render_rc=${PIPESTATUS[0]}
[ "$render_rc" -eq 0 ] || fail "③ 今日 One Loop 未 complete（exit=${render_rc}）"
ONE_LOOP_STATUS="complete"
write_state running "target day is complete" >/dev/null || fail "无法记录 One Loop 完成状态"
say "ONE_LOOP_COMPLETE"
say "   —— 20 日门已处理；后续失败会保留门状态，但整轮不会报 DONE ——"

# ── 第 4-8 步：实盘决策线（可断可补）─────────────────────────────────────
L4="live_trading/_live_broad_${STAMP}.log"
begin_step "04_live_broad" "live broad scan"
say "④ 实盘广筛（56 支，--no-multi-agent --no-shadow）"
run_logged "$L4" "④" "$PY" paper_trading/test2_signal_runner.py \
  --universe live_trading/live_universe.json --no-multi-agent --no-shadow
say "   $(grep -o '股票池 .* 陈旧剔除 [0-9]*' "$L4" | tail -1 || true)"

begin_step "05_funnel" "live subset funnel"
say "⑤ 漏斗"
SUB="live_trading/_live_subset_${DAY}.json"
"$PY" live_trading/live_subset.py "$DAY" 2>&1 | tee -a "$SUMMARY"
step_rc=${PIPESTATUS[0]}
[ "$step_rc" -eq 0 ] || fail "⑤ 漏斗命令失败（exit=${step_rc}）"
[ -f "$SUB" ] || fail "⑤ 子集未生成"

SYMS=$("$PY" -c "import json;print(','.join(s['symbol'] for s in json.load(open('$SUB'))['stocks']))") \
  || fail "⑤ 无法读取子集"
[ -n "$SYMS" ] || fail "⑤ 子集为空"

# ⑥ 标签：只刷子集、绝不带 --force（有效期 7 天，新鲜的自动跳过）。
L6="paper_trading/_longterm_labels_${STAMP}.log"
begin_step "06_labels" "refresh long-term labels"
say "⑥ 长期标签（只刷漏斗子集，不带 --force，fast 档，预算 120）"
run_logged "$L6" "⑥" env LOCAL_CLI_FORCE_FAST_TIER=true LOCAL_CLI_CALL_BUDGET=120 \
  "$PY" paper_trading/build_longterm_labels.py --timeout 300 \
  --universe live_trading/live_universe.json --symbols "$SYMS"
say "   $(grep -o '完成：.*' "$L6" | tail -1 || true)  调用 $(calls_of "$L6") 次"

# ⑦ 深评：只跑「标签非规避 ∪ 持仓」；规避是硬闸。
DEEP="live_trading/_live_deep_subset_${DAY}.json"
begin_step "07_deep" "build and run deep subset"
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
step_rc=${PIPESTATUS[0]}
[ "$step_rc" -eq 0 ] || fail "⑦ 无法构建深评子集（exit=${step_rc}）"

DEEP_N=$("$PY" -c "import json;print(len(json.load(open('$DEEP'))['stocks']))") \
  || fail "⑦ 无法读取深评子集"
L7="live_trading/_live_deep_${STAMP}.log"
if [ "$DEEP_N" -gt 0 ]; then
  say "⑦ 子集深评（$DEEP_N 支，multi-agent）"
  run_logged "$L7" "⑦" "$PY" paper_trading/test2_signal_runner.py \
    --universe "$DEEP" --multi-agent --no-shadow --workers 4
  say "   调用 $(calls_of "$L7") 次"
else
  say "⑦ 深评范围为空（全部规避且无持仓）→ 跳过"
fi

L8="paper_trading/_test2_ab_${STAMP}.log"
begin_step "08_ab" "AB replay"
say "⑧ AB 回放"
run_logged "$L8" "⑧" "$PY" paper_trading/test2_ab_runner.py --start 2026-07-03 --end "$DAY"
say "   $(tail -3 "$L8" | head -2 | tr '\n' ' ')"

# ── 汇总 ────────────────────────────────────────────────────────────────
TOTAL=0
for f in "$L1" "$L4" "$L6" "$L7"; do
  n=$(calls_of "$f")
  TOTAL=$((TOTAL + ${n:-0}))
done
say ""
say "=== 本轮 LLM 调用合计 ≈ ${TOTAL} 次（基线 142，目标 ≈95）==="
CURRENT_STEP="done"
write_state complete "pipeline finished" --llm-calls "$TOTAL" >/dev/null \
  || fail "无法写入最终结构化状态"
say "产物：$L1 / $L4 / $L6 / $L7 / $L8 / $SUB / $DEEP / $STATE"
say "PIPELINE_DONE"
