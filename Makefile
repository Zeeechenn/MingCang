# StockSage 常用命令封装
# 用法：make <target>，例如 `make test`、`make dev`

PYTHON ?= $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python3)
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff
MYPY ?= $(PYTHON) -m mypy
PRE_COMMIT ?= $(PYTHON) -m pre_commit
UV ?= uv
PIP_AUDIT ?= $(PYTHON) -m pip_audit
UV_CACHE_DIR ?= /tmp/stocksage-uv-cache
RUFF_CACHE_DIR ?= /tmp/stocksage-ruff-cache
MYPY_CACHE_DIR ?= /tmp/stocksage-mypy-cache
PYTEST_CACHE_DIR ?= /tmp/stocksage-pytest-cache
COVERAGE_FILE ?= /tmp/stocksage-coverage
COVERAGE_XML ?= coverage.xml
PIP_AUDIT_CACHE_DIR ?= /tmp/stocksage-pip-audit-cache

.PHONY: help install python-sync python-lock python-lock-check precommit-install test coverage frontend-test frontend-lint frontend-format-check lint security dependency-audit fmt typecheck check verify dev build coverage-snapshot agent-setup agent agent-dev agent-mcp agent-mcp-config clean docker-build docker-up docker-down

help:
	@echo "StockSage Makefile commands:"
	@echo "  install      安装依赖（含 dev 工具链）"
	@echo "  python-sync  按 uv.lock 同步 Python dev 环境"
	@echo "  python-lock  更新 uv.lock"
	@echo "  python-lock-check 检查 uv.lock 是否与 pyproject 同步"
	@echo "  precommit-install 安装 Git pre-commit hooks"
	@echo "  test         跑后端测试套件"
	@echo "  coverage     跑后端测试并输出覆盖率报告"
	@echo "  frontend-test 跑前端 node:test 单元测试"
	@echo "  frontend-lint 跑前端 ESLint（当前 advisory，不纳入 verify）"
	@echo "  frontend-format-check 跑前端 Prettier 配置文件检查"
	@echo "  lint         ruff 检查（不修复）"
	@echo "  security     ruff 安全规则快照（当前不作为硬门槛）"
	@echo "  dependency-audit Python 依赖漏洞审计"
	@echo "  fmt          ruff format + ruff fix"
	@echo "  typecheck    mypy 类型检查"
	@echo "  check        lint + typecheck + test 一键全跑（PR 前用）"
	@echo "  verify       后端/前端/构建全量验证"
	@echo "  coverage-snapshot 输出当前数据覆盖快照"
	@echo "  agent-setup  配置 StockSage 原生 Pi/agent 本地运行环境"
	@echo "  agent        启动 StockSage 原生 Pi 研究型终端 agent"
	@echo "  agent-dev    启动 StockSage 原生 Pi 开发型终端 agent"
	@echo "  agent-mcp    启动 StockSage MCP stdio 工具桥"
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

coverage:
	COVERAGE_FILE=$(COVERAGE_FILE) PYTHONPATH=. $(PYTEST) -q -o cache_dir=$(PYTEST_CACHE_DIR) --cov=backend --cov-report=term-missing --cov-report=xml:$(COVERAGE_XML)

frontend-test:
	cd frontend && node --test src/*.test.js src/components/*.test.js src/pages/*.test.js

frontend-lint:
	cd frontend && npm run lint

frontend-format-check:
	cd frontend && npm run format:check

lint:
	$(RUFF) check backend tests --cache-dir $(RUFF_CACHE_DIR)

security:
	$(RUFF) check backend --select S --ignore S101,S311 --exit-zero --statistics --cache-dir $(RUFF_CACHE_DIR)

dependency-audit:
	$(PIP_AUDIT) --cache-dir $(PIP_AUDIT_CACHE_DIR) --progress-spinner off --desc off --skip-editable

fmt:
	$(RUFF) format backend tests
	$(RUFF) check --fix backend tests --cache-dir $(RUFF_CACHE_DIR)

typecheck:
	$(MYPY) backend --cache-dir $(MYPY_CACHE_DIR)

check: lint typecheck test

verify: lint typecheck test frontend-test build

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
