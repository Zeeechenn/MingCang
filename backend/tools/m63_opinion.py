"""M63-2 opinion feed CLI (喂观点).

The daily router's ``_opinion_change_stub`` in ``backend.tools.m63_daily`` is
intentionally left inert.  R4 opinion-change entries are generated here at feed
time: the raw opinion is archived first, then an optional LLM comparison against
watchlist theses enqueues ``R4_opinion_change`` directly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from backend.research.watchlist import WATCHLIST_DIR, load_watchlists
from backend.workflows.m63_daily import DEFAULT_QUEUE_PATH, _enqueue, load_queue, save_queue
from backend.workflows.render import sanitize_trade_words

DEFAULT_OPINIONS_PATH = Path.home() / ".mingcang" / "m63_opinions.jsonl"

_SYSTEM_PROMPT = (
    "你是明仓研究助理。任务是把用户新喂入的一段观点,和现有观察哨主题 thesis 做差异比较。"
    "只判断观点是否会改变主题跟踪强度,不要给交易指令。"
)

_OPINION_TOOL = {
    "name": "m63_opinion_change",
    "input_schema": {
        "type": "object",
        "properties": {
            "affected_themes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "theme_key": {"type": "string"},
                        "stance_change": {
                            "type": "string",
                            "enum": ["none", "strengthened", "weakened", "reversed", "new_theme"],
                        },
                        "summary": {"type": "string"},
                    },
                    "required": ["theme_key", "stance_change", "summary"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["affected_themes"],
        "additionalProperties": False,
    },
}


@contextmanager
def _forced_claude_env():
    updates = {"LOCAL_CLI_PREFER_CODEX": "false", "LOCAL_CLI_NO_CODEX_FALLBACK": "true"}
    old = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _today() -> str:
    return date.today().isoformat()


def _read_text_arg(file: str | None, text: str | None) -> str:
    if file:
        return Path(file).read_text(encoding="utf-8")
    return text or ""


def archive_opinion(
    *,
    text: str,
    source: str,
    as_of: str,
    opinions_path: Path = DEFAULT_OPINIONS_PATH,
) -> dict[str, Any]:
    row = {
        "ts_date": as_of,
        "source": source,
        "text": text[:8000],
    }
    opinions_path.parent.mkdir(parents=True, exist_ok=True)
    with opinions_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _prompt(opinion: dict[str, Any], watchlists: list[dict[str, Any]]) -> str:
    compact = [
        {
            "theme_key": item.get("theme_key"),
            "title": item.get("title"),
            "thesis": item.get("thesis"),
            "symbols": item.get("symbols"),
        }
        for item in watchlists
    ]
    return (
        "新观点:\n"
        + json.dumps(opinion, ensure_ascii=False)
        + "\n\n现有观察哨主题:\n"
        + json.dumps(compact, ensure_ascii=False)
        + "\n\n输出受影响主题。若观点只是泛泛重复、无法映射、或不改变 thesis 强弱, stance_change=none。"
    )


def analyze_opinion(opinion: dict[str, Any], *, watchlist_dir: Path | str = WATCHLIST_DIR) -> dict[str, Any]:
    from backend.llm.factory import get_provider

    watchlists, errors = load_watchlists(watchlist_dir)
    with _forced_claude_env():
        data = get_provider().complete_structured(
            prompt=_prompt(opinion, watchlists),
            tool=_OPINION_TOOL,
            system=_SYSTEM_PROMPT,
            max_tokens=700,
            model_tier="capable",
        )
    if not data:
        raise RuntimeError("LLM returned empty opinion analysis")
    data.setdefault("watchlist_errors", errors)
    return data


def enqueue_opinion_changes(
    analysis: dict[str, Any],
    *,
    source: str,
    as_of: str,
    queue_path: Path = DEFAULT_QUEUE_PATH,
) -> list[dict[str, Any]]:
    queue = load_queue(queue_path)
    enqueued: list[dict[str, Any]] = []
    for item in analysis.get("affected_themes", []) or []:
        if not isinstance(item, dict):
            continue
        change = str(item.get("stance_change") or "none")
        if change == "none":
            continue
        target = str(item.get("theme_key") or "").strip()
        if not target:
            continue
        summary = sanitize_trade_words(str(item.get("summary") or "").strip())[0]
        if _enqueue(
            queue,
            as_of=as_of,
            target=target,
            reason=f"观点变化({source}): {summary}"[:240],
            trigger_rule="R4_opinion_change",
        ):
            enqueued.append(queue[-1])
    save_queue(queue, queue_path)
    return enqueued


def run_opinion(
    *,
    text: str,
    source: str = "manual",
    as_of: str | None = None,
    no_llm: bool = False,
    opinions_path: Path = DEFAULT_OPINIONS_PATH,
    queue_path: Path = DEFAULT_QUEUE_PATH,
) -> dict[str, Any]:
    day = as_of or _today()
    opinion = archive_opinion(text=text, source=source, as_of=day, opinions_path=opinions_path)
    if no_llm:
        print("已存档,未分析(无LLM)")
        return {"opinion": opinion, "analysis": None, "enqueued": []}
    try:
        analysis = analyze_opinion(opinion)
    except Exception as exc:  # noqa: BLE001 - archive path must succeed without LLM.
        print(f"已存档,未分析(无LLM): {type(exc).__name__}: {exc}")
        return {"opinion": opinion, "analysis": None, "enqueued": []}
    enqueued = enqueue_opinion_changes(analysis, source=source, as_of=day, queue_path=queue_path)
    print(json.dumps({"archived": True, "enqueued": enqueued}, ensure_ascii=False, indent=2))
    return {"opinion": opinion, "analysis": analysis, "enqueued": enqueued}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feed an M63 opinion into watchlist thesis comparison")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", default=None, help="观点文本文件")
    group.add_argument("--text", default=None, help="观点内容")
    parser.add_argument("--source", default="manual", help="观点来源名")
    parser.add_argument("--as-of", default=None, help="日期 YYYY-MM-DD")
    parser.add_argument("--no-llm", action="store_true", help="仅归档,不分析")
    args = parser.parse_args(argv)
    text = _read_text_arg(args.file, args.text).strip()
    if not text:
        print("观点内容为空", file=sys.stderr)
        return 2
    run_opinion(text=text, source=args.source, as_of=args.as_of, no_llm=args.no_llm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
