"""本地 CLI LLM Provider（本地开发替代 API key）

默认优先通过 `codex exec` 调用当前 CLI 会话；当 `LOCAL_CLI_PREFER_CODEX=false`
时才先尝试 `claude -p`，并在 Claude 不可用时回退到 Codex。
生产环境切换回 openai/anthropic provider 即可。
"""
import functools
import json
import logging
import os
import re
import subprocess
import time

from backend.config import settings
from backend.llm.base import LLMFatalResult as _FatalResult
from backend.llm.base import LLMProvider

logger = logging.getLogger(__name__)


def _model_for_tier(model_tier: str) -> str:
    # LOCAL_CLI_FORCE_FAST_TIER=true 把 capable 档也压到 fast（haiku）。
    # 用于日常跑批：一次跑测试是 O(百) 次调用，capable 档的那几个位置
    # （track_analyst / discretion / researcher）会显著抬高订阅额度消耗。
    # 默认关闭 —— 生产与单跑研究不受影响；降档会降低这些位置的判断质量，
    # 只在"跑通比跑准更重要"的批处理里开。
    if model_tier == "capable" and not _force_fast_tier():
        return settings.local_cli_model_capable
    return settings.local_cli_model_fast


def _force_fast_tier() -> bool:
    return os.environ.get("LOCAL_CLI_FORCE_FAST_TIER", "").strip().lower() in ("1", "true", "yes")


# 额度耗尽时 claude CLI 不会挂起，而是秒回一句人话（returncode != 0）。
# 2026-08-20 之前这被 _extract_json 当成"输出非 JSON"的可恢复错误，于是每个调用
# 重试满 3 次、且没有任何全局熔断——一个跑批会为剩下的每一支标的重复付出
# 3 次子进程 + 6s sleep（实测 m63_postmarket 空转 3 小时 / 572 次徒劳调用），
# 更糟的是上层把这些空结果当"降级"静默写进产物（标签作业 25/25"完成"，
# 其中 131 次调用其实是失败值）。
_QUOTA_MARKERS = (
    "reached your usage limit",
    "usage limit reached",
    "exceeded your usage limit",
    "out of usage",
    "已达到使用上限",
    "额度已用尽",
)

_quota_tripped_at: float | None = None


def _looks_like_quota_exhaustion(*chunks: str) -> bool:
    blob = " ".join(c for c in chunks if c).lower()
    return any(marker in blob for marker in _QUOTA_MARKERS)


def quota_guard_tripped() -> bool:
    """本进程是否已判定 claude CLI 额度耗尽。

    跑批脚本应在每个标的之后检查它：一旦为真，继续跑只会产出降级值污染产物，
    正确做法是停下并如实报告"已完成 N / 未完成 M"。
    """
    return _quota_tripped_at is not None


def reset_quota_guard() -> None:
    """额度恢复后清除熔断（无需重启进程）。"""
    global _quota_tripped_at
    _quota_tripped_at = None


def _trip_quota_guard(source: str) -> None:
    global _quota_tripped_at
    if _quota_tripped_at is None:
        _quota_tripped_at = time.time()
        logger.critical(
            "LLM_QUOTA_EXHAUSTED %s：claude CLI 额度耗尽，本进程后续调用一律短路。"
            "已产出的结果里可能含降级值，不要当成正常产物；额度恢复后调用 "
            "reset_quota_guard() 或重跑。",
            source,
        )


def _cli_retry(max_attempts: int = 3, delay: float = 2.0):
    """子进程调用失败时指数退避重试。

    仅对"返回空 JSON"（模型输出格式错误等可恢复错误）重试。
    _FatalResult 异常由 complete_structured 在超时/不可恢复时抛出，
    _cli_retry 直接返回其 result，不触发重试——避免 3×90s 放大效应。
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    result = fn(*args, **kwargs)
                except _FatalResult as e:
                    return e.result
                if result:
                    return result
                if attempt < max_attempts - 1:
                    wait = delay * (2 ** attempt)
                    logger.warning("LocalCLI 返回空结果（第%d次），%.1fs后重试",
                                   attempt + 1, wait)
                    time.sleep(wait)
            return {}
        return wrapper
    return decorator


class LocalCLIProvider(LLMProvider):
    """
    通过本地 Codex / Claude Code CLI 调用 LLM，无需项目 API key。

    使用方式：在 .env 中设置 AI_PROVIDER=local_cli。
    生产时改回 AI_PROVIDER=openai 或 AI_PROVIDER=anthropic。
    """

    def __init__(self, timeout: int = 90) -> None:
        """Initialize with subprocess timeout in seconds."""
        self._timeout = timeout

    @_cli_retry(max_attempts=3, delay=2.0)
    def complete_structured(
        self,
        prompt: str,
        tool: dict,
        system: str = "",
        max_tokens: int = 400,
        model_tier: str = "fast",
    ) -> dict:
        """通过本地 CLI 子进程调用 LLM，强制返回符合 tool schema 的 JSON。"""
        schema_str = json.dumps(tool["input_schema"], ensure_ascii=False, indent=2)
        tool_name = tool["name"]

        parts = []
        if system:
            parts.append(system.strip())
        parts.append(prompt.strip())
        parts.append(
            f"\n请严格按照以下 JSON Schema 输出函数 `{tool_name}` 的参数。"
            "只输出 JSON 对象本身，不要加任何解释文字或 markdown 代码块：\n"
            + schema_str
        )
        full_prompt = "\n\n".join(parts)

        if settings.local_cli_prefer_codex:
            return self._complete_with_codex(full_prompt)

        # Clean single-model guard: when LOCAL_CLI_NO_CODEX_FALLBACK=true, a Claude
        # failure (quota/timeout) must NOT silently fall back to Codex — that would
        # pollute a single-model (sonnet) OOS leg with codex scores. Failures return {}
        # (recorded as missing/neutral, uncached upstream) + a greppable marker.
        # Default-off, so production is unaffected.
        no_codex_fallback = os.environ.get("LOCAL_CLI_NO_CODEX_FALLBACK", "").strip().lower() in ("1", "true", "yes")

        if quota_guard_tripped():
            # 已知额度耗尽：不再 spawn 子进程，也不重试。
            raise _FatalResult({}) from None

        try:
            claude = subprocess.run(
                ["claude", "-p", "--model", _model_for_tier(model_tier), "--output-format", "text"],
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            if claude.returncode != 0:
                logger.warning("LocalCLI Claude stderr: %s", claude.stderr[:300])
            if _looks_like_quota_exhaustion(claude.stdout, claude.stderr):
                _trip_quota_guard("claude -p")
                if no_codex_fallback:
                    raise _FatalResult({}) from None
                raise _FatalResult(self._complete_with_codex(full_prompt)) from None
            data = self._extract_json(claude.stdout)
            if data:
                return data
            # Claude 可用但输出非 JSON（格式错误），尝试 Codex 兜底
            if no_codex_fallback:
                logger.warning("OOS_LLM_FAILED LocalCLIProvider Claude: 输出非 JSON，已禁用 codex 兜底")
                return {}
            return self._complete_with_codex(full_prompt)
        except subprocess.TimeoutExpired:
            # 超时 = CLI 挂住（配额耗尽/限速）。
            # 尝试 Codex 一次（不同服务，不受同一配额影响），
            # 然后抛 _FatalResult 告知 _cli_retry 不再重试，避免 3×90s 放大。
            logger.warning(
                "LocalCLIProvider Claude: 超时（%ds），prompt_len=%d；"
                "可能是日配额耗尽",
                self._timeout, len(full_prompt),
            )
            if no_codex_fallback:
                logger.warning("OOS_LLM_FAILED LocalCLIProvider Claude: 超时且已禁用 codex 兜底")
                raise _FatalResult({}) from None
            raise _FatalResult(self._complete_with_codex(full_prompt)) from None
        except FileNotFoundError:
            logger.warning("LocalCLIProvider: `claude` 命令未找到，尝试 Codex CLI")
            if no_codex_fallback:
                raise _FatalResult({}) from None
            return self._complete_with_codex(full_prompt)
        except _FatalResult:
            raise
        except Exception as e:
            logger.warning("LocalCLIProvider: 调用异常: %s", e)
            return {}

    def _complete_with_codex(self, full_prompt: str) -> dict:
        """Fallback to Codex CLI when Claude CLI is unavailable or logged out."""
        # Optional reasoning-effort override. Codex's configured default is xhigh,
        # which is slow + token-heavy + hang-prone for a trivial classification call.
        # Set LOCAL_CLI_CODEX_EFFORT (e.g. "medium") to override; unset = codex's own
        # config, so production is unaffected. Also disable MCP servers (-c
        # mcp_servers={}) to avoid the Notion/Figma auth handshake that can hang exec.
        cmd = [
            "codex", "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "-s", "read-only",
            "-c", "mcp_servers={}",
        ]
        effort = os.environ.get("LOCAL_CLI_CODEX_EFFORT", "").strip()
        if effort:
            cmd += ["-c", f"model_reasoning_effort={effort}"]
        cmd.append("-")
        try:
            proc = subprocess.run(
                cmd,
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            if proc.returncode != 0:
                logger.warning("LocalCLI Codex stderr: %s", proc.stderr[:300])
            return self._extract_json(proc.stdout)
        except subprocess.TimeoutExpired:
            logger.warning("LocalCLIProvider Codex: 超时（%ds）", self._timeout)
            return {}
        except FileNotFoundError:
            logger.error("LocalCLIProvider: `codex` 命令未找到")
            return {}
        except Exception as e:
            logger.warning("LocalCLIProvider Codex: 调用异常: %s", e)
            return {}

    @staticmethod
    def _extract_json(text: str) -> dict:
        """从 CLI 输出中提取第一个完整 JSON 对象，兼容 markdown 代码块。"""
        if not text:
            return {}
        # 去掉 ```json ... ``` 或 ``` ... ```
        text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            logger.warning("LocalCLI: 输出中未找到 JSON (前200字符): %s", text[:200])
            return {}
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # 尝试修复截断的 JSON
            open_b = candidate.count("{") - candidate.count("}")
            open_br = candidate.count("[") - candidate.count("]")
            repaired = candidate + "]" * max(0, open_br) + "}" * max(0, open_b)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                logger.warning("LocalCLI: JSON 修复失败 (前200字符): %s", candidate[:200])
                return {}
