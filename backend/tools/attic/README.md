# backend/tools/attic — 已归档的一次性脚本

本目录存放确认**零引用**的一次性脚本。

归档判定(P1-4,fix/safe-layer 分支,2026-06-07):

- 仅归档在**整个仓库**(`backend/` + `tests/`)中既无 `from backend.tools.<module> import`
  也无 `import backend.tools.<module>`、且无配套测试的脚本。
- 当前仅 2 个满足:`backfill_and_run.py`、`rerun_failed_6.py`。

**为何 backend/tools/ 下其余 m26 / m27 / m29 / m31 / m41 / m42 / m45 系列脚本未归档:**
它们看似一次性里程碑脚本,但**几乎每个都带配套 `tests/test_*.py`**(或被生产代码
import)。原评审报告"tools 目录臃肿 = 一堆死代码"的判断不成立——这些是有测试覆盖
的真实工具,移动会破坏测试收集/运行,故保留原位。

如需复活归档脚本:把对应 `.py` 移回 `backend/tools/` 即可,其依赖均在原位。
