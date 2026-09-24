# Model-comparison acceptance contract

Task-scoped contract for the experimental model-comparison work. It is not a
second plan or authorization. Queue and economic prerequisites are in
[ROADMAP](../ROADMAP.md); observed state is in [STATUS](../../STATUS.md).
Historical handoff: [09-19 repair and GPT-6 treatment-arm share](https://chatgpt.com/s/cx_6aae84dca0748191952c0184a48990af).

## Fixed scope and current state

- Existing authorization covers public-pool inputs, two destinations, a fixed
  25-symbol universe, a virtual account, and at most 60 periods. The shared v2
  ledger is 1 reserved / 59 remaining. Do not change this denominator or retry
  the 09-16 failed raw arm, the 09-22 missing session, or any failed period.
- The approved non-economic channel check may run at 23:00 on a later eligible
  workday under that scope. It checks invocation, isolation, records, failures,
  provider identity and usage receipts; it is not a NAV replay or strategy test.
  Price-basis drift does not block this channel check.
- v2 and its frozen runner remain unchanged; the runner resets cash each period.
  The v3 candidate is `prepared_not_activated`, default-off, and fake-only. Its
  fixed-pool validation, immutable request bytes, and read-only registration/hash
  preflight do not reserve a slot, call a model, or connect to a database.
  Caller-supplied source-review hashes do not verify source authenticity.
- There is no successful real paired response, resolved-provider receipt,
  billing evidence, or economic treatment. Local candidate/architecture tests
  establish engineering behavior only.

## Non-economic call contract

Before each authorized call, freeze the question, exact visible input, baseline
version and hashes, prompt/tools, cutoff, window, reserved slot, and failure
policy. Capture actual requested and resolved provider identity and usage in the
receipt; do not guess identity beforehand or silently fall back. Preserve each
failure in the fixed denominator. Authentication or quota failure ends that
attempt. No retry, substitution, or refund; never overwrite an attempt. Store
actual visible input plus request/response bytes and hashes, cutoff, failures,
and usage. An allowed package does not prove what the model actually saw.

This gate does not test NAV, strategy, or economic value. Keep each arm's memory
filtered to its cutoff; future prices/actions/answers and the other arm's answer
must not enter context. Historical Claude traces remain separate. Session
reservation is exclusive and precedes the call; a failed or interrupted attempt
still consumes its reservation. A known over-limit or corrupted arm blocks new
calls.

## Economic gate and limits

Economic replay remains blocked until trusted raw prices and corporate actions,
source/calendar truth, continuous account isolation, actual provider/usage/
billing receipts, and a separate owner/economic approval are established.
Do not treat token fields of zero as proof of zero usage or cost. Do not create a
second ledger, database, scheduler, or consume a different experiment's budget.

If later comparisons are separately authorized, preserve the question order:
same GPT-6 raw/desk for MingCang increment; then Claude/GPT-6 at the same desk;
then one workflow change with same model/data. Use two arms by default, not a
four-arm mixed comparison. Keep the full-market/fixed-25 universe trial separate
from those comparisons and from a daily run.

Manifest v2 binds candidate family, parameters, count, nested forward folds,
label-span purge/embargo, and holdout. An unfinished attempt blocks reads; a
failed read still consumes its reservation. After a read is reserved, no new
model call is allowed. There is no stable-promotion path in this contract.

The process wrapper bounds local input/output/time, process groups, backpressure,
and partial-output retention; macOS restricts write paths and protected reads
and prevents runtime-key inheritance. These checks do not guarantee remote
cancellation, a hard billing cap, whole-account isolation, or an unseen
holdout. Engineering validation is not source truth, PIT evidence, or experiment
authorization.

Rollback is to stop invoking the added CLI and remove its adapter. No DB
migration, production maintenance, or rewriting/restating the old five-session
protocol is part of rollback.

## Bundle, expiry, and later economic reporting

The existing explicit offline consumer accepts a `matched_model_replay.v1` bundle
and emits input-hashed diagnostic NAV, fills/rejections, failure rate and cost
gaps. Missing price basis or action coverage means no simulated-return claim. This
trial expires 2026-12-31; expiry does not extend authorization. The 20-period run
check and 60-period cap are operational controls, not alpha/statistical thresholds.

After data and separate launch gates pass, keep any economic comparison to one
changed variable and one new common window. The full-window result is primary;
retain failures under the preregistered rule and show success-only results as
auxiliary. Report fee-net active return, IR, actual NAV, drawdown/tail,
turnover/cost, exposure and industry/single-name contribution concentration, plus
uncertainty. For stock-days use block bootstrap by symbol/date; overlapping
observations are not independent. Do not add post-sale upside directly to portfolio
return. Freeze cash, executable buy-and-hold and simple-rule baselines. Each round
retains the frozen spec, per-call visible input/decision, complete ledger,
benchmarks, costs, failures, and a supported / unsupported / insufficient-evidence
conclusion. Twenty periods checks operations; sixty is only a directional check.
