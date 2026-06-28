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
from backend.llm.base import LLMProvider

logger = logging.getLogger(__name__)


def _model_for_tier(model_tier: str) -> str:
    if model_tier == "capable":
        return settings.local_cli_model_capable
    return settings.local_cli_model_fast


class _FatalResult(Exception):
    """非可重试错误（子进程超时等），携带已计算的最终结果直接返回。"""
    def __init__(self, result: dict) -> None:
        self.result = result


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
            data = self._extract_json(claude.stdout)
            if data:
                return data
            # Claude 可用但输出非 JSON（格式错误），尝试 Codex 兜底
            return self._complete_with_codex(full_prompt)
        except subprocess.TimeoutExpired:
            # 超时 = CLI 挂住（配额耗尽/限速）。
            # 尝试 Codex 一次（不同服务，不受同一配额影响），
            # 然后抛 _FatalResult 告知 _cli_retry 不再重试，避免 3×90s 放大。
            logger.warning(
                "LocalCLIProvider Claude: 超时（%ds），prompt_len=%d；"
                "可能是日配额耗尽，尝试 Codex 兜底后不再重试",
                self._timeout, len(full_prompt),
            )
            raise _FatalResult(self._complete_with_codex(full_prompt)) from None
        except FileNotFoundError:
            logger.warning("LocalCLIProvider: `claude` 命令未找到，尝试 Codex CLI")
            return self._complete_with_codex(full_prompt)
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
