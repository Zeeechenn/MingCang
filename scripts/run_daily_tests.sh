#!/usr/bin/env bash
# 明仓「跑测试」每日流水线（SOP 的可执行版本）。
#
# 两条 track 解耦跑（2026-08-25 起）：
#   Track A（One Loop 20 日门）= ①②③⑧
#   Track B（实盘决策线）      = ④⑤⑥⑦，跑前先过它自己的行情数据门
#     （scripts/live_track_gate.py：0=通过 5=未过→跳过⑤⑥⑦ 其他=用法/IO错误）
# 两条 track 互不阻塞彼此的中止：一条 aborted/skipped 不会拖累另一条继续跑。
# 只有真正的 LLM 账号额度熔断（LLM_QUOTA_EXHAUSTED / 额度耗尽）才会让整轮立刻
# 停手——两条 track 都没有继续的意义。
#
# --no-shadow、m63 的 --no-llm、标签不带 --force 且先于深评等额度纪律固定在这里。
#
# 用法：bash scripts/run_daily_tests.sh [YYYY-MM-DD] [--one-loop-only]
#   不传日期 = 今天。收盘后跑（数据必须已定盘）。参数位置无关。
#   --one-loop-only：只跑 Track A（①②③⑧），完全不碰 Track B（④⑤⑥⑦，含⑥标签
#   120 次预算和⑦ multi-agent 深评）。用于 20 日门当天没过、需要同日重跑到过
#   门为止，又不想为此重烧 Track B 的 LLM 额度。成功打 ONE_LOOP_ONLY_DONE
#   （exit 0），失败打 PIPELINE_ABORTED（exit 1）——两种情况都绝不打
#   PIPELINE_DONE：Track B 是有意没跑，不是跑完了。此模式下 summary 追加不
#   截断、state 不删，前一次尝试的记录留在文件里（同日重跑安全）。
#   ①④⑥⑦ 的跑手（test2_signal_runner.py / build_longterm_labels.py）没有
#   --date 参数，永远只跑「今天」；传历史日期会在这里直接拒绝（exit 2），
#   补跑历史日请单独手工处理。仅测试/开发场景可设 MINGCANG_ALLOW_NON_TODAY=1
#   跳过这道检查。
set -uo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${MINGCANG_REPO_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
cd "$REPO" || exit 1
PY="${MINGCANG_PYTHON:-$REPO/.venv/bin/python3}"
ONE_LOOP_ONLY=false
DAY=""
for arg in "$@"; do
  case "$arg" in
    --one-loop-only)
      ONE_LOOP_ONLY=true
      ;;
    *)
      [ -z "$DAY" ] && DAY="$arg"
      ;;
  esac
done
DAY="${DAY:-$(date +%F)}"
[[ "$DAY" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
  || { echo "PIPELINE_ABORTED: 日期必须为 YYYY-MM-DD"; exit 2; }
if [ "$DAY" != "$(date +%F)" ] && [ "${MINGCANG_ALLOW_NON_TODAY:-0}" != "1" ]; then
  echo "PIPELINE_ABORTED: ①④⑥⑦ 的跑手（test2_signal_runner.py / build_longterm_labels.py）没有 --date 参数，永远只跑当天（$(date +%F)），收到目标日 $DAY 不是今天；补跑历史日请单独手工处理。仅测试/开发场景可设 MINGCANG_ALLOW_NON_TODAY=1 跳过此检查。"
  exit 2
fi
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
  # $1=step 名 $2=消息 $3=可选 track（one_loop|live）
  CURRENT_STEP="$1"
  local extra=()
  [ -n "${3:-}" ] && extra=(--track "$3")
  write_state running "$2" "${extra[@]}" >/dev/null || fail "无法更新结构化运行状态：$STATE"
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

# 额度熔断哨兵：真账号额度耗尽时立刻停手全脚本（重跑只会在恢复瞬间再打空一次），
# 两条 track 都没有继续的意义。只认这两个标记——本进程预算用尽的
# LLM_CALL_BUDGET_EXHAUSTED 不在此列，见下面的 budget_check。
quota_check() {
  if grep -q "LLM_QUOTA_EXHAUSTED\|额度耗尽" "$1" 2>/dev/null; then
    fail "$2 触发 LLM 额度熔断，后续步骤全部跳过，不要重跑，等额度恢复"
  fi
}

# 本进程调用预算（例如⑥的 LOCAL_CLI_CALL_BUDGET=120）用尽时打的是
# LLM_CALL_BUDGET_EXHAUSTED，这不是账号额度耗尽，不中止——只在 summary 里
# 打一条醒目提示，该步骤的成败仍由它自己的退出码决定。
budget_check() {
  if grep -q "LLM_CALL_BUDGET_EXHAUSTED" "$1" 2>/dev/null; then
    say "⚠ $2 用满了本步预算，标签可能没刷全，不是账号额度问题"
  fi
}

# 每个作业退出时会打 LLM_CALL_TOTAL，汇总它便于事后核账。
calls_of() {
  local value
  value=$(grep -o "LLM_CALL_TOTAL claude 调用 [0-9]*" "$1" 2>/dev/null \
    | grep -o "[0-9]*" | tail -1 || true)
  printf '%s' "${value:-0}"
}

# 非致命命令执行：记日志、跑真额度/预算哨兵，返回真实退出码——不 fail() 整个脚本。
# 命令失败与否由调用方决定属于哪条 track 的 aborted。
run_step() {
  local log="$1" label="$2" rc
  shift 2
  "$@" > "$log" 2>&1
  rc=$?
  quota_check "$log" "$label"
  budget_check "$log" "$label"
  return $rc
}

# 把某条 track 判定为 aborted：记原因、落一笔结构化状态（best-effort，不因为
# 这笔状态写入失败而拖垮另一条 track 的评估）。
mark_track_failed() {
  write_state aborted "$2" --track "$1" >/dev/null 2>&1 || true
}

# 把某条 track 标成「有意未尝试」（不是失败）：--one-loop-only 模式下 Track B
# 完全没跑。update_daily_pipeline_state.py 的 --status 只接受
# running|aborted|complete，没有专门语义——complete 会误导成「跑完了」，所以
# 沿用实盘数据门未过时 skip 的既有写法：status 留 running（不设
# finished_at），靠 message 讲清楚是主动跳过、不是失败也不是还在跑。
mark_track_not_attempted() {
  write_state running "$2" --track "$1" >/dev/null 2>&1 || true
}

if $ONE_LOOP_ONLY; then
  # 同日重跑保护：不截断 summary、不删 state，前一次尝试的记录留在文件里。
  say "=== 重跑 Track A（--one-loop-only） $(date +%H:%M:%S) ==="
else
  : > "$SUMMARY"
  rm -f "$STATE"
fi
say "=== 明仓跑测试 $DAY ==="
write_state running "pipeline started" >/dev/null || fail "无法初始化结构化运行状态：$STATE"

# ── Track A：①②③⑧（One Loop 20 日门 + AB 回放）────────────────────────
TRACK_A_OK=true
TRACK_A_REASON=""
STEP1_FULL=false
L1="" L2="" L8="" SNAP="" AUDIT_JSON="" L3_SNAPSHOT="" L3_AUDIT=""

abort_track_a() {
  TRACK_A_OK=false
  TRACK_A_REASON="${TRACK_A_REASON:+$TRACK_A_REASON; }$1"
  mark_track_failed one_loop "$1"
  say "⛔ $1"
}

run_track_a_123() {
  L1="paper_trading/_test2_${STAMP}.log"
  begin_step "01_test2" "test2 official batch" "one_loop"
  say "① test2 官方批次（25 支，--no-shadow）"
  if ! run_step "$L1" "①" "$PY" paper_trading/test2_signal_runner.py --no-shadow; then
    abort_track_a "① 命令失败，见 $L1"; return 1
  fi
  if ! grep -q "产信号 25 · 跳过 0 · 失败 0" "$L1"; then
    abort_track_a "① 未达 25/25，见 $L1"; return 1
  fi
  if ! grep -q "data_date==${DAY}" "$L1"; then
    abort_track_a "① 数据日不是 ${DAY}（可能未收盘或行情缺失），见 $L1"; return 1
  fi
  # 支数够但数据日不是当天（跑早了/行情未定盘）同样不能喂进⑧：那是一批
  # 完整但停留在旧数据日的信号。所以 STEP1_FULL 立在两道校验都过之后。
  STEP1_FULL=true
  say "   ✅ 25/25，data_date==${DAY}；本步 LLM 调用 $(calls_of "$L1") 次"

  L2="paper_trading/_m63_postmarket_${STAMP}.log"
  begin_step "02_postmarket" "One Loop postmarket panel" "one_loop"
  say "② One Loop 盘后面板（--no-llm，0 次调用）"
  if ! run_step "$L2" "②" "$PY" -m backend.tools.m63_daily \
      --mode postmarket --date "$DAY" --no-llm; then
    abort_track_a "② 命令失败，见 $L2"; return 1
  fi
  if ! grep -q "postmarket_${DAY}.md" "$L2"; then
    abort_track_a "② 面板未落盘，见 $L2"; return 1
  fi
  say "   ✅ 面板已写"

  begin_step "03_one_loop" "One Loop continuity audit" "one_loop"
  say "③ One Loop 审计"
  SNAP="$RUN_DIR/audit.db"
  AUDIT_JSON="$RUN_DIR/one_loop.json"
  L3_SNAPSHOT="$RUN_DIR/snapshot.log"
  L3_AUDIT="$RUN_DIR/one_loop_audit.log"
  if ! run_step "$L3_SNAPSHOT" "③-快照" "$PY" scripts/sqlite_consistent_snapshot.py \
      --source "$REPO/mingcang.db" --destination "$SNAP"; then
    abort_track_a "③-快照 命令失败，见 $L3_SNAPSHOT"; return 1
  fi
  if ! run_step "$L3_AUDIT" "③-审计" "$PY" scripts/audit_one_loop_continuity.py \
      --db "$SNAP" --implementation-since 2026-08-19 --output "$AUDIT_JSON"; then
    abort_track_a "③-审计 命令失败，见 $L3_AUDIT"; return 1
  fi
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
  if [ "$render_rc" -ne 0 ]; then
    abort_track_a "③ 今日 One Loop 未 complete（exit=${render_rc}）"; return 1
  fi
  ONE_LOOP_STATUS="complete"
  write_state running "target day is complete" --track one_loop >/dev/null \
    || fail "无法记录 One Loop 完成状态"
  say "ONE_LOOP_COMPLETE"
  say "   —— 20 日门已处理；后续失败会保留门状态，但整轮不会报 DONE ——"
  return 0
}

run_track_a_123

# ⑧ AB 回放挪进 Track A：只在①拿到 25/25 时才跑——test2_ab_data.load_signals
# 只做「同日取最后一版」，当天只有 21 支也照样回放且不报错，所以完整性必须由
# 这里挡，不能指望 AB 回放自己发现数据不全。是否跑⑧与②③是否通过无关。
if $STEP1_FULL; then
  L8="paper_trading/_test2_ab_${STAMP}.log"
  begin_step "08_ab" "AB replay" "one_loop"
  say "⑧ AB 回放（当日 test2 批次完整，25/25）"
  if run_step "$L8" "⑧" "$PY" paper_trading/test2_ab_runner.py --start 2026-07-03 --end "$DAY"; then
    say "   $(tail -3 "$L8" | head -2 | tr '\n' ' ')"
  else
    abort_track_a "⑧ 命令失败，见 $L8"
  fi
else
  say "⑧ 跳过：当日 test2 批次未完整通过①（支数不足或数据日不是当天），不喂进 AB 回放"
fi

if $TRACK_A_OK; then
  TRACK_A_FINAL="ok"
else
  TRACK_A_FINAL="aborted"
fi

# ── Track B：④⑤⑥⑦（实盘决策线）+ 它自己的数据门 ─────────────────────────
TRACK_B_ABORTED=false
TRACK_B_SKIPPED=false
TRACK_B_REASON=""
L4="" L6="" L7="" SUB="" DEEP="" GATE_JSON=""

abort_track_b() {
  TRACK_B_ABORTED=true
  TRACK_B_REASON="${TRACK_B_REASON:+$TRACK_B_REASON; }$1"
  mark_track_failed live "$1"
  say "⛔ $1"
}

if $ONE_LOOP_ONLY; then
  # --one-loop-only：Track B（④⑤⑥⑦）有意完全不跑，省下它的 LLM 额度
  # （⑥ 120 次预算 + ⑦ multi-agent 深评）。不是失败，是没尝试。
  CURRENT_STEP="track_b_not_attempted"
  say "④⑤⑥⑦ 跳过：--one-loop-only 只跑 Track A，Track B 本轮未尝试"
  mark_track_not_attempted live "Track B (④⑤⑥⑦) not attempted: --one-loop-only 主动跳过，非失败"
  TRACK_B_FINAL="not_attempted"
else

L4="live_trading/_live_broad_${STAMP}.log"
begin_step "04_live_broad" "live broad scan" "live"
say "④ 实盘广筛（56 支，--no-multi-agent --no-shadow）"
if run_step "$L4" "④" "$PY" paper_trading/test2_signal_runner.py \
    --universe live_trading/live_universe.json --no-multi-agent --no-shadow; then
  say "   $(grep -o '股票池 .* 陈旧剔除 [0-9]*' "$L4" | tail -1 || true)"
else
  abort_track_b "④ 命令失败，见 $L4"
fi

if [ "$TRACK_B_ABORTED" = false ]; then
  begin_step "04b_live_gate" "live track data gate" "live"
  say "   实盘数据门（覆盖率 + 持仓行情陈旧检测）"
  GATE_JSON="$RUN_DIR/live_gate.json"
  GATE_LOG="$RUN_DIR/live_gate.log"
  "$PY" scripts/live_track_gate.py --date "$DAY" --json-out "$GATE_JSON" > "$GATE_LOG" 2>&1
  gate_rc=$?
  write_state running "live track gate evaluated (exit=${gate_rc})" \
    --track live --gate-json "$GATE_JSON" >/dev/null 2>&1 || true
  if [ "$gate_rc" -eq 0 ]; then
    say "   ✅ 实盘数据门通过（见 ${GATE_JSON}）"
  elif [ "$gate_rc" -eq 5 ]; then
    TRACK_B_SKIPPED=true
    say "LIVE_TRACK_SKIPPED: 行情门未过（见 ${GATE_JSON}）"
  else
    abort_track_b "实盘数据门用法/IO 错误（exit=${gate_rc}），见 $GATE_LOG"
  fi
fi

run_track_b_567() {
  # ⑤ 漏斗
  begin_step "05_funnel" "live subset funnel" "live"
  say "⑤ 漏斗"
  SUB="live_trading/_live_subset_${DAY}.json"
  "$PY" live_trading/live_subset.py "$DAY" 2>&1 | tee -a "$SUMMARY"
  local step_rc=${PIPESTATUS[0]}
  if [ "$step_rc" -ne 0 ]; then
    abort_track_b "⑤ 漏斗命令失败（exit=${step_rc}）"; return 1
  fi
  if [ ! -f "$SUB" ]; then
    abort_track_b "⑤ 子集未生成"; return 1
  fi

  SYMS=$("$PY" -c "import json;print(','.join(s['symbol'] for s in json.load(open('$SUB'))['stocks']))")
  if [ $? -ne 0 ]; then
    abort_track_b "⑤ 无法读取子集"; return 1
  fi
  if [ -z "$SYMS" ]; then
    abort_track_b "⑤ 子集为空"; return 1
  fi

  # ⑥ 标签：只刷子集、绝不带 --force（有效期 7 天，新鲜的自动跳过）。
  L6="paper_trading/_longterm_labels_${STAMP}.log"
  begin_step "06_labels" "refresh long-term labels" "live"
  say "⑥ 长期标签（只刷漏斗子集，不带 --force，fast 档，预算 120）"
  if ! run_step "$L6" "⑥" env LOCAL_CLI_FORCE_FAST_TIER=true LOCAL_CLI_CALL_BUDGET=120 \
      "$PY" paper_trading/build_longterm_labels.py --timeout 300 \
      --universe live_trading/live_universe.json --symbols "$SYMS"; then
    abort_track_b "⑥ 命令失败，见 $L6"; return 1
  fi
  say "   $(grep -o '完成：.*' "$L6" | tail -1 || true)  调用 $(calls_of "$L6") 次"

  # ⑦ 深评：只跑「标签非规避 ∪ 持仓」；规避是硬闸。
  DEEP="live_trading/_live_deep_subset_${DAY}.json"
  begin_step "07_deep" "build and run deep subset" "live"
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
  local step7_rc=${PIPESTATUS[0]}
  if [ "$step7_rc" -ne 0 ]; then
    abort_track_b "⑦ 无法构建深评子集（exit=${step7_rc}）"; return 1
  fi

  DEEP_N=$("$PY" -c "import json;print(len(json.load(open('$DEEP'))['stocks']))")
  if [ $? -ne 0 ]; then
    abort_track_b "⑦ 无法读取深评子集"; return 1
  fi
  L7="live_trading/_live_deep_${STAMP}.log"
  if [ "$DEEP_N" -gt 0 ]; then
    say "⑦ 子集深评（$DEEP_N 支，multi-agent）"
    if ! run_step "$L7" "⑦" "$PY" paper_trading/test2_signal_runner.py \
        --universe "$DEEP" --multi-agent --no-shadow --workers 4; then
      abort_track_b "⑦ 命令失败，见 $L7"; return 1
    fi
    say "   调用 $(calls_of "$L7") 次"
  else
    say "⑦ 深评范围为空（全部规避且无持仓）→ 跳过"
  fi
  return 0
}

if [ "$TRACK_B_ABORTED" = false ] && [ "$TRACK_B_SKIPPED" = false ]; then
  run_track_b_567
fi

if [ "$TRACK_B_ABORTED" = true ]; then
  TRACK_B_FINAL="aborted"
elif [ "$TRACK_B_SKIPPED" = true ]; then
  TRACK_B_FINAL="skipped"
else
  TRACK_B_FINAL="ok"
fi

fi  # end: else branch of `if $ONE_LOOP_ONLY` (Track B execution)

# ── 汇总 ────────────────────────────────────────────────────────────────
TOTAL=0
for f in "$L1" "$L4" "$L6" "$L7"; do
  n=$(calls_of "$f")
  TOTAL=$((TOTAL + ${n:-0}))
done
say ""
say "=== 本轮 LLM 调用合计 ≈ ${TOTAL} 次 ==="
say ""
say "=== Track 结果 ==="
if [ "$TRACK_A_FINAL" = ok ]; then
  say "Track A（One Loop ①②③⑧）：✅ 成功"
else
  say "Track A（One Loop ①②③⑧）：⛔ aborted — ${TRACK_A_REASON:-见上方日志}"
fi
if [ "$TRACK_B_FINAL" = ok ]; then
  say "Track B（实盘 ④⑤⑥⑦）：✅ 成功"
elif [ "$TRACK_B_FINAL" = skipped ]; then
  say "Track B（实盘 ④⑤⑥⑦）：⏭ skipped — 行情门未过（见 ${GATE_JSON:-无}）"
elif [ "$TRACK_B_FINAL" = not_attempted ]; then
  say "Track B（实盘 ④⑤⑥⑦）：⏭ 未尝试 — --one-loop-only 主动跳过"
else
  say "Track B（实盘 ④⑤⑥⑦）：⛔ aborted — ${TRACK_B_REASON:-见上方日志}"
fi

CURRENT_STEP="done"
say "产物：$L1 / $L4 / $L6 / $L7 / $L8 / $SUB / $DEEP / $STATE"
if $ONE_LOOP_ONLY; then
  # 这个模式下 Track B 是有意未尝试，绝不能打 PIPELINE_DONE（那意味着两条
  # track 都跑完了）。也不复用 PIPELINE_PARTIAL：那表示「有东西失败了」，
  # 这里是「没打算跑」，语义不同。
  if [ "$TRACK_A_FINAL" = ok ]; then
    write_state complete "one-loop-only run finished (Track B not attempted: --one-loop-only)" \
      --llm-calls "$TOTAL" >/dev/null || fail "无法写入最终结构化状态"
    say "ONE_LOOP_ONLY_DONE"
    exit 0
  else
    write_state aborted "PIPELINE_ABORTED: track A=$TRACK_A_FINAL (${TRACK_A_REASON:-见日志}); track B=not_attempted (--one-loop-only)" \
      --llm-calls "$TOTAL" >/dev/null || fail "无法写入最终结构化状态"
    say "PIPELINE_ABORTED"
    exit 1
  fi
elif [ "$TRACK_A_FINAL" = ok ] && [ "$TRACK_B_FINAL" = ok ]; then
  write_state complete "pipeline finished" --llm-calls "$TOTAL" >/dev/null \
    || fail "无法写入最终结构化状态"
  say "PIPELINE_DONE"
  exit 0
elif [ "$TRACK_A_FINAL" = ok ] || [ "$TRACK_B_FINAL" = ok ]; then
  write_state aborted "PIPELINE_PARTIAL: track A=$TRACK_A_FINAL (${TRACK_A_REASON:-ok}); track B=$TRACK_B_FINAL (${TRACK_B_REASON:-ok})" \
    --llm-calls "$TOTAL" >/dev/null || fail "无法写入最终结构化状态"
  say "PIPELINE_PARTIAL"
  exit 4
else
  write_state aborted "PIPELINE_ABORTED: track A=$TRACK_A_FINAL (${TRACK_A_REASON:-见日志}); track B=$TRACK_B_FINAL (${TRACK_B_REASON:-见日志})" \
    --llm-calls "$TOTAL" >/dev/null || fail "无法写入最终结构化状态"
  say "PIPELINE_ABORTED"
  exit 1
fi
