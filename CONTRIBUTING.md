# Contributing to StockSage

> **注意**：本项目目前为个人量化研究工具，代码已 MIT 开源。欢迎 issue 反馈和 PR 贡献，但合并决策由维护者把关。

---

## 快速开始

```bash
git clone <repo-url> && cd stock-sage
pip install -e ".[dev]"        # 安装开发依赖（pytest + ruff + mypy）
pre-commit install              # 安装 pre-commit hooks
cp .env.example .env           # 填入 ANTHROPIC_API_KEY
python3 backend/data/database.py
```

---

## 开发规范

### 代码风格

- **格式化**：ruff format（等同 Black，line-length=100）
- **Lint**：ruff check，已配置规则见 `pyproject.toml`
- **类型**：新函数加 return type 注解；复杂参数加 `from __future__ import annotations`
- **注释**：只在 WHY 非显然时加注释；模块级 docstring 简短说明模块职责

### 测试

```bash
PYTHONPATH=. pytest -q          # 全量用例应全部通过
PYTHONPATH=. pytest tests/test_kill_switch.py -v  # 单文件
```

- 每个新功能或 bug fix 必须附测试
- 集成测试放 `tests/integration/`，单元测试放 `tests/`
- 回测相关测试不依赖实时网络（用 fixture 或 mock 数据）

### 核心约束（不可违反）

- **止盈止损由 ATR 公式计算**，任何路径不得让 LLM 直接输出价格
- **LLM 只做情感分析**（`sentiment.py`），不做价格预测
- **所有信号附置信度**，前端必须显示
- **单股仓位 ≤ 15%，单板块 ≤ 30%，总权益 ≤ 80%**

---

## 提交 PR

1. 从 `main` 创建功能分支：`git checkout -b feat/your-feature`
2. 开发并确保 `pytest -q` 通过
3. `git push origin feat/your-feature` 后打开 PR
4. PR 描述说明：做了什么 / 为什么 / 测试覆盖了什么

---

## 任务编号

新任务用 **M{X}.{Y}** 格式（如 M7.B3）。里程碑体系见 `PROJECT.md`，详细计划见 `docs/ROADMAP.md`。
