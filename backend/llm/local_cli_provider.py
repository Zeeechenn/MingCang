"""本地 CLI LLM Provider（本地开发替代 API key）

优先通过 `claude -p` 子进程调用当前 CLI 会话；若 Claude CLI 未登录，
回退到 `codex exec`。
生产环境切换回 openai/anthropic provider 即可。
"""
import functools
import json
import logging
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


def _cli_retry(max_attempts: int = 3, delay: float = 2.0):
    """子进程调用失败时指数退避重试"""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                result = fn(*args, **kwargs)
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
    通过本地 Claude Code / Codex CLI 调用 LLM，无需项目 API key。

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
            return self._complete_with_codex(full_prompt)
        except subprocess.TimeoutExpired:
            logger.warning("LocalCLIProvider: 超时（%ds）", self._timeout)
            return {}
        except FileNotFoundError:
            logger.warning("LocalCLIProvider: `claude` 命令未找到，尝试 Codex CLI")
            return self._complete_with_codex(full_prompt)
        except Exception as e:
            logger.warning("LocalCLIProvider: 调用异常: %s", e)
            return {}

    def _complete_with_codex(self, full_prompt: str) -> dict:
        """Fallback to Codex CLI when Claude CLI is unavailable or logged out."""
        try:
            proc = subprocess.run(
                [
                    "codex", "exec",
                    "--ephemeral",
                    "--skip-git-repo-check",
                    "-s", "read-only",
                    "-",
                ],
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
