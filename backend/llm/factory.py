import logging
from backend.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_instance: LLMProvider | None = None


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

    from backend.config import settings

    provider = settings.ai_provider.lower()

    if provider == "local_cli":
        from backend.llm.local_cli_provider import LocalCLIProvider
        _instance = LocalCLIProvider()
        logger.info("LLM provider: LocalCLI (claude -p subprocess, no API key needed)")
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
