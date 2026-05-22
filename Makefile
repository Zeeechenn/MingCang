# StockSage 常用命令封装
# 用法：make <target>，例如 `make test`、`make dev`

PYTHON ?= $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python3)
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff
MYPY ?= $(PYTHON) -m mypy
PRE_COMMIT ?= $(PYTHON) -m pre_commit

.PHONY: help install precommit-install test frontend-test lint fmt typecheck check verify dev build coverage-snapshot paper-stats agent-setup agent agent-dev agent-mcp agent-mcp-config clean docker-build docker-up docker-down

help:
	@echo "StockSage Makefile commands:"
	@echo "  install      安装依赖（含 dev 工具链）"
	@echo "  precommit-install 安装 Git pre-commit hooks"
	@echo "  test         跑后端测试套件"
	@echo "  frontend-test 跑前端 node:test 单元测试"
	@echo "  lint         ruff 检查（不修复）"
	@echo "  fmt          ruff format + ruff fix"
	@echo "  typecheck    mypy 类型检查"
	@echo "  check        lint + typecheck + test 一键全跑（PR 前用）"
	@echo "  verify       后端/前端/构建全量验证"
	@echo "  coverage-snapshot 输出当前数据覆盖快照"
	@echo "  paper-stats  统计纸面交易结果"
	@echo "  agent-setup  配置 StockSage pi/agent 本地运行环境"
	@echo "  agent        启动 StockSage pi 研究型终端 agent"
	@echo "  agent-dev    启动 StockSage pi 开发型终端 agent"
	@echo "  agent-mcp    启动 StockSage MCP stdio 工具桥"
	@echo "  agent-mcp-config 输出 MCP 客户端配置片段"
	@echo "  dev          启动后端 dev server (uvicorn --reload)"
	@echo "  build        前端 vite 构建"
	@echo "  clean        清理 __pycache__ / .pytest_cache / dist"
	@echo "  docker-build 构建 docker 镜像"
	@echo "  docker-up    docker compose up（启动 backend + frontend）"
	@echo "  docker-down  docker compose down"

install:
	$(PIP) install ".[dev]"
	cd frontend && npm install

precommit-install:
	$(PRE_COMMIT) install

test:
	PYTHONPATH=. $(PYTEST) -q

frontend-test:
	cd frontend && node --test src/*.test.js src/components/*.test.js src/pages/*.test.js

lint:
	$(RUFF) check backend tests

fmt:
	$(RUFF) format backend tests
	$(RUFF) check --fix backend tests

typecheck:
	$(MYPY) backend

check: lint typecheck test

verify: lint typecheck test frontend-test build

dev:
	PYTHONPATH=. $(PYTHON) -m uvicorn backend.main:app --reload

build:
	cd frontend && npm run build

coverage-snapshot:
	PYTHONPATH=. $(PYTHON) -m backend.tools.coverage_snapshot

paper-stats:
	PYTHONPATH=. $(PYTHON) -m paper_trading.stats

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
	rm -rf .pytest_cache .ruff_cache .mypy_cache frontend/dist

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down
