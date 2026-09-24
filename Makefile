# MingCang 常用命令封装
# 用法：make <target>，例如 `make test`、`make dev`

PYTHON ?= $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python3)
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff
MYPY ?= $(PYTHON) -m mypy
PRE_COMMIT ?= $(PYTHON) -m pre_commit
UV ?= uv
PIP_AUDIT ?= $(PYTHON) -m pip_audit
UV_CACHE_DIR ?= /tmp/mingcang-uv-cache
RUFF_CACHE_DIR ?= /tmp/mingcang-ruff-cache
MYPY_CACHE_DIR ?= /tmp/mingcang-mypy-cache
PYTEST_CACHE_DIR ?= /tmp/mingcang-pytest-cache
COVERAGE_FILE ?= /tmp/mingcang-coverage
COVERAGE_XML ?= coverage.xml
PIP_AUDIT_CACHE_DIR ?= /tmp/mingcang-pip-audit-cache

.PHONY: help install python-sync python-lock python-lock-check precommit-install test coverage frontend-test frontend-lint frontend-smoke lint hygiene doc-check security dependency-audit release-check fmt typecheck check verify demo reproduce-evidence dev build coverage-snapshot agent-setup agent agent-dev agent-mcp agent-mcp-config clean docker-build docker-up docker-down research-test research-check

help:
	@echo "MingCang Makefile commands:"
	@echo "  install      安装依赖（含 dev 工具链）"
	@echo "  python-sync  按 uv.lock 同步 Python dev 环境"
	@echo "  python-lock  更新 uv.lock"
	@echo "  python-lock-check 检查 uv.lock 是否与 pyproject 同步"
	@echo "  precommit-install 安装 Git pre-commit hooks"
	@echo "  test         跑后端测试套件"
	@echo "  research-test 跑显式行情源与新闻快照的真实历史流程；需要 MARKET_SOURCE NEWS_SNAPSHOT INDUSTRY_METADATA DECISION_DATES OUT_DIR；FACTOR_SOURCE 可选"
	@echo "  research-check 跑新闻与股票池联合离线回归；可用 OUT_DIR 指定输出目录"
	@echo "  coverage     跑后端测试并输出覆盖率报告"
	@echo "  frontend-test 跑前端 node:test 单元测试"
	@echo "  frontend-lint 跑前端 ESLint（阻塞式，全量输出）"
	@echo "  frontend-smoke 跑 demo / live / 部分实时浏览器冒烟"
	@echo "  lint         ruff 检查（不修复）"
	@echo "  hygiene      发布卫生守卫（旧名词/个人路径/凭据模式）"
	@echo "  doc-check    文档权威/nav/README 中英一致性检查"
	@echo "  security     ruff 安全规则快照（当前不作为硬门槛）"
	@echo "  dependency-audit Python 依赖漏洞审计"
	@echo "  release-check 校验后端/前端/包版本一致性（可传 TAG=vX.Y.Z）"
	@echo "  fmt          ruff format + ruff fix"
	@echo "  typecheck    mypy 类型检查"
	@echo "  check        lint + typecheck + test 一键全跑（PR 前用）"
	@echo "  verify       后端/前端/构建全量验证（ESLint 错误会阻塞）"
	@echo "  demo         种子演示数据库并启动后端 + 前端 demo（无需真实 API Key）"
	@echo "  reproduce-evidence 离线打印 demo 闭环证据（无网络/无 API Key）"
	@echo "  coverage-snapshot 输出当前数据覆盖快照"
	@echo "  agent-setup  配置 MingCang 原生 Pi/agent 本地运行环境"
	@echo "  agent        启动 MingCang 原生 Pi 研究型终端 agent"
	@echo "  agent-dev    启动 MingCang 原生 Pi 开发型终端 agent"
	@echo "  agent-mcp    启动 MingCang MCP stdio 工具桥"
	@echo "  agent-mcp-config 输出 MCP 客户端配置片段"
	@echo "  dev          启动后端 dev server (uvicorn --reload)"
	@echo "  build        前端 vite 构建"
	@echo "  clean        清理 __pycache__ / .pytest_cache / dist"
	@echo "  docker-build 构建 docker 镜像"
	@echo "  docker-up    docker compose up（启动 backend + frontend）"
	@echo "  docker-down  docker compose down"

install:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) sync --extra dev
	cd frontend && npm install

python-sync:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) sync --frozen --extra dev

python-lock:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) lock --python 3.11

python-lock-check:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) lock --check

precommit-install:
	$(PRE_COMMIT) install

test:
	PYTHONPATH=. $(PYTEST) -q -o cache_dir=$(PYTEST_CACHE_DIR)

research-test:
	@test -n "$(MARKET_SOURCE)" || { echo "research-test requires MARKET_SOURCE" >&2; exit 2; }
	@test -n "$(NEWS_SNAPSHOT)" || { echo "research-test requires NEWS_SNAPSHOT" >&2; exit 2; }
	@test -n "$(INDUSTRY_METADATA)" || { echo "research-test requires INDUSTRY_METADATA" >&2; exit 2; }
	@test -n "$(DECISION_DATES)" || { echo "research-test requires DECISION_DATES (comma-separated YYYY-MM-DD)" >&2; exit 2; }
	@test -n "$(OUT_DIR)" || { echo "research-test requires OUT_DIR" >&2; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/research_checks/historical.py run --market-source "$(MARKET_SOURCE)" --news-snapshot "$(NEWS_SNAPSHOT)" --industry-metadata "$(INDUSTRY_METADATA)" --decision-dates "$(DECISION_DATES)" --out-dir "$(OUT_DIR)" $(if $(FACTOR_SOURCE),--factor-source "$(FACTOR_SOURCE)",)

research-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/research_checks/joint.py check $(if $(OUT_DIR),--out-dir "$(OUT_DIR)",)

coverage:
	COVERAGE_FILE=$(COVERAGE_FILE) PYTHONPATH=. $(PYTEST) -q -o cache_dir=$(PYTEST_CACHE_DIR) --cov=backend --cov-report=term-missing --cov-report=xml:$(COVERAGE_XML)

frontend-test:
	cd frontend && npm test

frontend-lint:
	cd frontend && npm run eslint

frontend-smoke:
	cd frontend && npm run smoke

lint:
	$(RUFF) check backend tests --cache-dir $(RUFF_CACHE_DIR)

hygiene:
	$(PYTHON) scripts/check_release_hygiene.py

doc-check:
	$(PYTHON) scripts/check_doc_authority.py

security:
	$(RUFF) check backend --select S --ignore S101,S311 --exit-zero --statistics --cache-dir $(RUFF_CACHE_DIR)

dependency-audit:
	$(PIP_AUDIT) --cache-dir $(PIP_AUDIT_CACHE_DIR) --progress-spinner off --desc off --skip-editable

release-check:
	$(PYTHON) scripts/check_release_consistency.py $(if $(TAG),--tag $(TAG),)

fmt:
	$(RUFF) format backend tests
	$(RUFF) check --fix backend tests --cache-dir $(RUFF_CACHE_DIR)

typecheck:
	$(MYPY) backend --cache-dir $(MYPY_CACHE_DIR)

check: lint hygiene doc-check typecheck test

verify: lint hygiene doc-check typecheck test frontend-test build frontend-lint frontend-smoke

demo:
	@echo "=== MingCang Demo Mode ==="
	@echo "Seeding demo DB at examples/sample_db/mingcang_demo.db ..."
	DATABASE_URL=sqlite:///$(shell pwd)/examples/sample_db/mingcang_demo.db \
		PYTHONPATH=. $(PYTHON) scripts/demo_seed.py
	@echo ""
	@echo "Demo DB ready."
	@echo "Backend:  http://127.0.0.1:8000"
	@echo "Frontend: http://127.0.0.1:5173"
	@echo "(Press Ctrl+C to stop both servers)"
	@set -e; \
	backend_pid=; \
	cleanup() { \
		if [ -n "$$backend_pid" ]; then \
			kill "$$backend_pid" 2>/dev/null || true; \
			wait "$$backend_pid" 2>/dev/null || true; \
		fi; \
	}; \
	trap cleanup EXIT INT TERM; \
	DATABASE_URL=sqlite:///$(shell pwd)/examples/sample_db/mingcang_demo.db \
		PYTHONPATH=. $(PYTHON) -m uvicorn backend.main:app --reload --port 8000 & \
	backend_pid=$$!; \
	sleep 2; \
	echo "Starting frontend dev server..."; \
	cd frontend && npm run dev -- --host 127.0.0.1

reproduce-evidence:
	DATABASE_URL=sqlite:///$(shell pwd)/examples/sample_db/mingcang_demo.db \
		PYTHONPATH=. $(PYTHON) scripts/reproduce_evidence.py

dev:
	PYTHONPATH=. $(PYTHON) -m uvicorn backend.main:app --reload

build:
	cd frontend && npm run build

coverage-snapshot:
	PYTHONPATH=. $(PYTHON) -m backend.tools.coverage_snapshot

agent-setup:
	bash scripts/agent_setup.sh

agent:
	bash scripts/agent_run.sh research

agent-dev:
	bash scripts/agent_run.sh dev

agent-mcp:
	PYTHONPATH=. $(PYTHON) -m backend.agent.mcp_server

agent-mcp-config:
	$(PYTHON) scripts/agent_mcp_config.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage coverage.xml frontend/dist

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down
