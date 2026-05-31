import logging
import shutil

from backend.config import settings
from backend.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_instance: LLMProvider | None = None


def _configured_secret(value: str | None) -> bool:
    """Return True only for non-placeholder runtime secrets."""
    if not value:
        return False
    normalized = value.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    return not (
        lowered.startswith("your_")
        or lowered in {"changeme", "change_me", "placeholder", "none", "null"}
    )


def runtime_readiness(runtime_settings=None) -> dict:
    """Return non-secret runtime LLM/search readiness for UI and health checks."""
    runtime_settings = settings if runtime_settings is None else runtime_settings
    provider_name = getattr(runtime_settings, "ai_provider", "local_cli")
    provider = provider_name.lower() if isinstance(provider_name, str) else "local_cli"
    claude_path = shutil.which("claude")
    codex_path = shutil.which("codex")

    usable = False
    reason = ""
    if provider == "local_cli":
        usable = bool(claude_path or codex_path)
        reason = "local CLI provider available" if usable else "Neither `claude` nor `codex` CLI was found on PATH"
    elif provider == "anthropic":
        usable = _configured_secret(getattr(runtime_settings, "anthropic_api_key", ""))
        reason = "Anthropic key configured" if usable else "ANTHROPIC_API_KEY is missing or still a placeholder"
    elif provider == "openai":
        usable = _configured_secret(getattr(runtime_settings, "openai_api_key", ""))
        reason = "OpenAI-compatible key configured" if usable else "OPENAI_API_KEY is missing or still a placeholder"
    else:
        reason = f"Unsupported AI_PROVIDER={provider}"

    return {
        "provider": provider,
        "usable": usable,
        "reason": reason,
        "local_cli": {
            "claude": bool(claude_path),
            "codex": bool(codex_path),
        },
        "search": {
            "tavily": _configured_secret(getattr(runtime_settings, "tavily_api_key", "")),
            "anspire": _configured_secret(getattr(runtime_settings, "anspire_api_key", "")),
        },
    }


def has_runtime_llm_provider(runtime_settings=None) -> bool:
    """Return whether the configured runtime LLM provider can be used."""
    return bool(runtime_readiness(runtime_settings)["usable"])


def get_provider() -> LLMProvider:
    """
    返回全局单例 LLMProvider。
    通过 .env 中的 AI_PROVIDER 切换：
      AI_PROVIDER=anthropic  （默认）
      AI_PROVIDER=openai
    """
    global _instance
    if _instance is not None:
        return _instance

    readiness = runtime_readiness(settings)
    if not readiness["usable"]:
        raise RuntimeError(f"LLM provider unavailable: {readiness['reason']}")

    provider = readiness["provider"]

    if provider == "local_cli":
        from backend.llm.local_cli_provider import LocalCLIProvider
        _instance = LocalCLIProvider(timeout=settings.local_cli_timeout_seconds)
        logger.info("LLM provider: LocalCLI (Codex/Claude CLI subprocess, no API key needed)")
    elif provider == "openai":
        from backend.llm.openai_provider import OpenAIProvider
        _instance = OpenAIProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        logger.info("LLM provider: OpenAI (base_url=%s)", settings.openai_base_url or "default")
    else:
        from backend.llm.anthropic_provider import AnthropicProvider
        _instance = AnthropicProvider(api_key=settings.anthropic_api_key)
        logger.info("LLM provider: Anthropic")

    return _instance



def reset_provider() -> None:
    """Clear the cached LLM provider. Tests call this after mutating settings."""
    global _instance
    _instance = None
