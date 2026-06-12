# Developer Guide

这页回答“怎么继续开发明仓”。普通用户先读 [User Guide](USER_GUIDE.md)，查功能先读 [Feature Map](FEATURE_MAP.md)。

## 1. 开发原则

- 先明确用户任务，再写页面或接口。
- 所有会写 DB、调用 provider、跑重任务、改配置的功能都要有确认边界。
- AI/LLM 默认是 shadow，不自动覆盖官方信号。
- 量化和研究实验默认 non-promoting。
- 新功能要能被 demo 或小样例解释清楚。

## 2. 加一个前端页面

1. 新增 `frontend/src/page-<name>.tsx` 页面（TypeScript）。
2. 在 `frontend/src/main.tsx` 增加路由和导航。
3. 在 `frontend/src/api.ts` 增加 API wrapper。
4. 把“是否写入/是否需确认”写到 UI 行为里。
5. 给复杂 helper 加测试。
6. 用 demo 数据跑一遍。

页面文案原则：

- 普通用户第一眼应知道这页能做什么。
- 休眠/影子功能不能包装成生产能力。
- 高风险动作要有确认。

## 3. 加一个后端 API

1. 找到对应 domain route，例如 `backend/api/routes/research.py`。
2. 在 `backend/api/schemas.py` 增加 schema。
3. 复用现有 service，不复制业务逻辑。
4. 写 focused tests。
5. 外部 provider 调用要说明 key、side effect 和失败模式。
6. 写操作要明确权限和确认路径。

## 4. 加一个 agent action

1. 在 `backend/agent/action_registry.py` 定义 action。
2. 给出 JSON schema。
3. 设置 risk level。
4. 默认 `requires_confirmation=True`。
5. handler 复用 API/service。
6. dry-run 返回足够清楚的 payload、risk 和 side effects。
7. 写 `tests/test_agent_action_registry.py` 相关测试。

标准流程：

```text
candidate -> dry-run -> human review -> confirm -> execute -> audit/result
```

## 5. 加一个研究模块

先判断它属于哪条 lane：

| Lane | 说明 | 可写入对象 |
|---|---|---|
| breadth | 扩展信息面，发现资料和候选论题 | ResearchState / Dossier / ForwardThesis draft |
| falsification | 找反例、失效条件和结果归因 | ReviewCase / scoreboard / MemoryPromotionCandidate |
| short-term risk | 风险纪律、止损、持仓和组合暴露 | risk warning / position context |

研究模块默认不改官方信号。需要 promotion 时必须有前向证据和用户确认。

## 6. 加一个量化模块

1. 写清假设和失败条件。
2. 先跑只读验证。
3. 报告 IC、ICIR、DSR/PBO、样本窗口和口径。
4. 输出 shadow evidence。
5. 不改 `weight_quant`。
6. 不改 production profile。
7. 不改 test2 baseline。

量化模块的默认身份是“证据生产者”，不是“自动荐股者”。

## 7. 加一个数据源

1. 放在 `backend/data/`。
2. 标明 market、coverage、freshness、adjustment、rate limit。
3. 接入 provider registry 或 explicit route。
4. 对可选外部源做 health/probe。
5. 默认不要悄悄进入正式信号。

## 8. 加文档

文档分工：

| 文档 | 职责 |
|---|---|
| `docs_public/index.md` | 文档站首页和导航。 |
| `docs_public/USER_GUIDE.md` | 使用路径和 demo walkthrough。 |
| `docs_public/FEATURE_MAP.md` | 所有功能逐项说明。 |
| `docs_public/DEVELOPER_GUIDE.md` | 后续开发规则。 |
| `docs_public/REFERENCE.md` | CLI/API/config reference。 |
| `docs_public/ARCHITECTURE.md` | L0-L4 架构。 |

## 9. 验证

最完整：

```bash
make verify
```

文档-only 最低检查：

```bash
git diff --check
```

涉及前端体验时，还要启动本地服务并看 demo 页面。
