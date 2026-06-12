"""Observe-only iFinD MCP client and parsers.

iFinD MCP is intentionally kept out of the production OHLCV fallback path.
The client here supports readiness probes and evidence extraction for research
flows without writing to the database or changing signal inputs.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from backend.config import settings

STOCK_MCP_ID = "hexin-ifind-ds-stock-mcp"
NEWS_MCP_ID = "hexin-ifind-ds-news-mcp"
INDEX_MCP_ID = "hexin-ifind-ds-index-mcp"
GLOBAL_STOCK_MCP_ID = "hexin-ifind-ds-global-stock-mcp"


@dataclass(frozen=True)
class IfindMcpResult:
    ok: bool
    text: str
    raw: dict[str, Any]
    error: str | None = None


class IfindMcpClient:
    """Minimal JSON-RPC client for iFinD MCP's HTTP transport."""

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.token = token if token is not None else settings.ifind_mcp_token
        self.base_url = (base_url or settings.ifind_mcp_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.ifind_mcp_timeout_seconds
        self._last_request_at = 0.0

    def _request(self, mcp_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            raise ValueError("IFIND_MCP_TOKEN is not configured")
        if not self.base_url:
            raise ValueError("IFIND_MCP_BASE_URL is not configured")
        self._respect_qps_limit()
        session = requests.Session()
        session.trust_env = False
        response = session.post(
            f"{self.base_url}/{mcp_id}",
            headers={"Authorization": self.token, "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            message = data["error"].get("message") if isinstance(data["error"], dict) else data["error"]
            raise RuntimeError(message or "iFinD MCP request failed")
        return data

    def _respect_qps_limit(self) -> None:
        qps_limit = float(settings.ifind_mcp_qps_limit)
        if qps_limit <= 0:
            return
        min_interval = 1.0 / qps_limit
        now = time.monotonic()
        wait_seconds = min_interval - (now - self._last_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
            now = time.monotonic()
        self._last_request_at = now

    def list_tools(self, mcp_id: str = STOCK_MCP_ID) -> list[dict[str, Any]]:
        data = self._request(mcp_id, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        return list((data.get("result") or {}).get("tools") or [])

    def call_tool(self, mcp_id: str, name: str, arguments: dict[str, Any]) -> IfindMcpResult:
        data = self._request(
            mcp_id,
            {
                "jsonrpc": "2.0",
                "id": "mingcang-ifind",
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        text_parts = []
        for item in (data.get("result") or {}).get("content") or []:
            if item.get("type") == "text":
                text_parts.append(str(item.get("text") or ""))
        text = "\n".join(text_parts)
        return IfindMcpResult(ok=True, text=text, raw=data)


def parse_markdown_tables(text: str) -> list[pd.DataFrame]:
    """Parse simple Markdown tables from iFinD MCP text responses."""
    tables: list[pd.DataFrame] = []
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if not line.startswith("|") or idx + 1 >= len(lines):
            idx += 1
            continue
        separator = lines[idx + 1].strip()
        if not re.fullmatch(r"\|?[\s:\-|]+\|?", separator):
            idx += 1
            continue
        block = [line]
        idx += 2
        while idx < len(lines) and lines[idx].strip().startswith("|"):
            block.append(lines[idx].strip())
            idx += 1
        rows = [[cell.strip() for cell in row.strip("|").split("|")] for row in block]
        if len(rows) >= 2:
            tables.append(pd.DataFrame(rows[1:], columns=rows[0]))
    return tables


def parse_embedded_json(text: str) -> Any:
    """Parse an iFinD response that is either JSON or a JSON string embedded in a wrapper."""
    payload = json.loads(text)
    if isinstance(payload, dict) and isinstance(payload.get("data"), str):
        try:
            return json.loads(payload["data"])
        except json.JSONDecodeError:
            return payload
    return payload


def parse_ifind_mcp_text(payload: Any) -> dict[str, Any]:
    """Return raw text plus best-effort JSON and Markdown-table parses."""
    text = _extract_text(payload).strip()
    return {
        "raw_text": text,
        "json": _parse_first_json(text),
        "tables": [
            {
                "headers": [str(col) for col in table.columns],
                "rows": table.astype(str).to_dict(orient="records"),
            }
            for table in parse_markdown_tables(text)
        ],
    }


def list_ifind_mcp_tools(mcp_id: str = STOCK_MCP_ID) -> dict[str, Any]:
    """List tools from an enabled iFinD MCP endpoint without writing local state."""
    started = time.perf_counter()
    if not settings.ifind_mcp_enabled:
        return {
            "ok": False,
            "enabled": False,
            "configured": bool(settings.ifind_mcp_token),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "mcp_id": mcp_id,
            "tools": [],
            "error": "IFIND_MCP_ENABLED=false",
        }
    try:
        tools = IfindMcpClient().list_tools(mcp_id)
        return {
            "ok": True,
            "enabled": bool(settings.ifind_mcp_enabled),
            "configured": bool(settings.ifind_mcp_token),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "mcp_id": mcp_id,
            "tools": [tool for tool in tools if isinstance(tool, dict)],
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "enabled": bool(settings.ifind_mcp_enabled),
            "configured": bool(settings.ifind_mcp_token),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "mcp_id": mcp_id,
            "tools": [],
            "error": str(exc),
        }


def call_ifind_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    mcp_id: str = STOCK_MCP_ID,
) -> dict[str, Any]:
    """Call an iFinD MCP tool and parse textual JSON/Markdown results."""
    started = time.perf_counter()
    if not settings.ifind_mcp_enabled:
        return {
            "ok": False,
            "enabled": False,
            "configured": bool(settings.ifind_mcp_token),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "mcp_id": mcp_id,
            "tool_name": tool_name,
            "result": None,
            "parsed": {"raw_text": "", "json": None, "tables": []},
            "error": "IFIND_MCP_ENABLED=false",
        }
    try:
        result = IfindMcpClient().call_tool(mcp_id, tool_name, arguments or {})
        return {
            "ok": True,
            "enabled": bool(settings.ifind_mcp_enabled),
            "configured": bool(settings.ifind_mcp_token),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "mcp_id": mcp_id,
            "tool_name": tool_name,
            "result": result.raw,
            "parsed": parse_ifind_mcp_text(result.text),
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "enabled": bool(settings.ifind_mcp_enabled),
            "configured": bool(settings.ifind_mcp_token),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "mcp_id": mcp_id,
            "tool_name": tool_name,
            "result": None,
            "parsed": {"raw_text": "", "json": None, "tables": []},
            "error": str(exc),
        }


def extract_stock_daily_table(text: str) -> pd.DataFrame:
    """Return a normalized single-day stock table when iFinD provides complete fields."""
    tables = parse_markdown_tables(text)
    if not tables:
        return pd.DataFrame()
    table = tables[0].copy()
    rename = {}
    for col in table.columns:
        if col == "日期":
            rename[col] = "date"
        elif col.startswith("开盘价"):
            rename[col] = "open"
        elif col.startswith("最高价"):
            rename[col] = "high"
        elif col.startswith("最低价"):
            rename[col] = "low"
        elif col.startswith("收盘价"):
            rename[col] = "close"
        elif col == "成交量":
            rename[col] = "volume"
    table = table.rename(columns=rename)
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(set(table.columns)):
        return pd.DataFrame()
    out = table[["date", "open", "high", "low", "close", "volume"]].copy()
    out["date"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["volume"] = out["volume"].map(_parse_number_with_cn_unit)
    return out.dropna(subset=["date", "close"]).set_index("date").sort_index()


def _parse_number_with_cn_unit(value: Any) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    multiplier = 1.0
    if text.endswith("万"):
        multiplier = 10_000.0
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000.0
        text = text[:-1]
    try:
        return float(text.replace(",", "")) * multiplier
    except ValueError:
        return None


def _extract_text(payload: Any) -> str:
    if isinstance(payload, IfindMcpResult):
        return payload.text
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        return "\n".join(_extract_text(item) for item in payload)
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, list):
            return _extract_text(content)
        text = payload.get("text")
        if isinstance(text, str):
            return text
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return str(payload) if payload is not None else ""


def _parse_first_json(text: str) -> Any | None:
    candidates = [text.strip()]
    candidates.extend(match.group(1).strip() for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.S | re.I))
    for candidate in candidates:
        if not candidate or candidate[0] not in "[{":
            continue
        try:
            return parse_embedded_json(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def probe_ifind_mcp() -> dict:
    """Run an explicit side-effect-free iFinD MCP readiness probe."""
    started = time.perf_counter()
    if not settings.ifind_mcp_enabled:
        return {
            "ok": False,
            "enabled": False,
            "configured": bool(settings.ifind_mcp_token),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "tool_count": 0,
            "error": "IFIND_MCP_ENABLED=false",
        }
    try:
        tools = IfindMcpClient().list_tools(STOCK_MCP_ID)
        return {
            "ok": True,
            "enabled": True,
            "configured": bool(settings.ifind_mcp_token),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "tool_count": len(tools),
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "enabled": True,
            "configured": bool(settings.ifind_mcp_token),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "tool_count": 0,
            "error": str(exc),
        }
