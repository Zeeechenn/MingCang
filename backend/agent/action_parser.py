"""Natural-language action candidate parsing for AI chat."""
from __future__ import annotations

import re
from hashlib import sha1

from sqlalchemy.orm import Session

from backend.data.database import Stock

ActionCandidate = tuple[str, dict]


def symbol_from_text(text: str) -> str | None:
    match = re.search(r"\b(\d{6})\b", text)
    return match.group(1) if match else None


def name_after_symbol(text: str, symbol: str) -> str | None:
    tail = text.split(symbol, 1)[-1].strip()
    if not tail:
        return None
    tail = re.split(r"[，,。；;\s]+", tail)[0].strip()
    return tail or None


def summary_after_marker(message: str, markers: tuple[str, ...], *, fallback: str) -> str:
    for marker in markers:
        if marker in message:
            tail = message.split(marker, 1)[-1].strip(" ：:，,。；;")
            if tail:
                return tail
    return fallback


def detect_action(message: str, db: Session) -> ActionCandidate | None:
    symbol = symbol_from_text(message)
    lower = message.lower()

    threshold_match = re.search(r"(?:阈值|threshold)\D*(\d+(?:\.\d+)?)", message, flags=re.I)
    if threshold_match and any(
        word in message for word in ("设置", "改", "调整", "update", "set")
    ):
        return "config.update", {
            "new_framework_entry_threshold": float(threshold_match.group(1)),
        }

    bool_map = {
        "多 Agent": "multi_agent_enabled",
        "多agent": "multi_agent_enabled",
        "长期分析师团": "long_term_team_enabled",
        "风险经理": "risk_manager_enabled",
        "移动止损": "trailing_stop_enabled",
        "大盘择时": "regime_filter_enabled",
        "ADX": "adx_filter_enabled",
    }
    for label, key in bool_map.items():
        if label in message and any(
            word in message for word in ("开启", "打开", "启用", "关闭", "禁用")
        ):
            enabled = any(word in message for word in ("开启", "打开", "启用"))
            return "config.update", {key: enabled}

    if "每日复盘" in message and any(
        word in message for word in ("触发", "生成", "运行", "跑")
    ):
        return "review.daily.ensure", {}
    if "长期复盘" in message and any(
        word in message for word in ("触发", "生成", "运行", "跑")
    ):
        return "review.long_term.ensure", {}

    mem_match = re.match(
        r"^\s*(?:请\s*)?(?:把|帮我)?\s*"
        r"(?:记住|记下来|存进记忆|存到记忆|保存为记忆)\s*[:：，,]?\s*(.+)$",
        message,
    )
    if mem_match:
        body = mem_match.group(1).strip()
        if body:
            if any(w in body for w in ("规则", "rule")):
                category = "rule"
            elif any(w in body for w in ("偏好", "preference")):
                category = "preference"
            elif any(w in body for w in ("风险", "risk", "预警")):
                category = "risk"
            else:
                category = "preference"
            digest = sha1(  # noqa: S324 - stable chat memory key, not security-sensitive.
                body.encode("utf-8")
            ).hexdigest()[:10]
            key = f"chat:{category}:{digest}"
            return "memory.write", {
                "key": key,
                "value": body,
                "category": category,
                "scope": "global",
                "symbol": symbol,
            }

    if not symbol:
        return None

    if any(
        word in message
        for word in ("调研过", "研究过", "做过调研", "做了调研", "调研了")
    ):
        return "stock_memory.write", {
            "symbol": symbol,
            "memory_type": "research_pointer",
            "summary": message.strip(),
            "status": "watching",
            "importance": 4,
            "confidence": 0.75,
        }

    thesis_markers = ("投资逻辑是", "逻辑是", "结论是", "thesis is", "thesis 是")
    if any(marker in lower for marker in ("thesis is",)) or any(
        marker in message for marker in thesis_markers
    ):
        summary = summary_after_marker(message, thesis_markers, fallback=message.strip())
        return "stock_memory.write", {
            "symbol": symbol,
            "memory_type": "thesis",
            "summary": f"{symbol} thesis：{summary}",
            "status": "watching",
            "importance": 4,
            "confidence": 0.75,
        }

    risk_markers = ("风险是", "风险点是", "担心点是", "预警是")
    if any(marker in message for marker in risk_markers) or any(
        word in message for word in ("风险", "预警", "担心")
    ):
        summary = summary_after_marker(message, risk_markers, fallback=message.strip())
        return "stock_memory.write", {
            "symbol": symbol,
            "memory_type": "risk",
            "summary": f"{symbol} 风险：{summary}",
            "status": "watching",
            "importance": 4,
            "confidence": 0.75,
        }

    if any(word in message for word in ("催化", "公告", "订单", "事件")) and any(
        word in message for word in ("有", "出现", "发生", "发布", "披露")
    ):
        summary = summary_after_marker(
            message,
            ("有", "出现", "发生", "发布", "披露"),
            fallback=message.strip(),
        )
        return "stock_memory.write", {
            "symbol": symbol,
            "memory_type": "event",
            "summary": f"{symbol} 事件：{summary}",
            "status": "watching",
            "importance": 3,
            "confidence": 0.7,
        }

    if any(word in message for word in ("删除自选", "移除自选", "取消关注")):
        return "watchlist.remove", {"symbol": symbol}

    if any(
        word in message
        for word in ("添加持仓", "新增持仓", "买入了", "已买入", "持仓")
    ):
        qty_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:股|shares?)", message, flags=re.I)
        cost_match = re.search(
            r"(?:成本|均价|avg|price)\s*[:：]?\s*(\d+(?:\.\d+)?)",
            message,
            flags=re.I,
        )
        if qty_match and cost_match:
            stock = db.query(Stock).filter(Stock.symbol == symbol).first()
            return "position.add", {
                "symbol": symbol,
                "name": stock.name if stock else name_after_symbol(message, symbol),
                "market": stock.market if stock else "CN",
                "quantity": float(qty_match.group(1)),
                "avg_cost": float(cost_match.group(1)),
            }
        # qty or cost missing — fall through to check other intent branches

    if any(
        word in message for word in ("添加自选", "加入自选", "关注", "重点跟踪")
    ) or "add watch" in lower:
        stock = db.query(Stock).filter(Stock.symbol == symbol).first()
        return "watchlist.add", {
            "symbol": symbol,
            "name": stock.name if stock else (name_after_symbol(message, symbol) or symbol),
            "market": stock.market if stock else "CN",
        }

    return None
