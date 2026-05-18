import logging
import time
import functools
import anthropic
from backend.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_MODELS = {
    "fast":    "claude-sonnet-4-6",
    "capable": "claude-sonnet-4-6",
}


def _llm_retry(max_attempts: int = 3, delay: float = 2.0):
    """LLM 调用指数退避重试"""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                result = fn(*args, **kwargs)
                if result:
                    return result
                if attempt < max_attempts - 1:
                    wait = delay * (2 ** attempt)
                    logger.warning("%s 返回空结果（第%d次），%.1fs后重试",
                                   fn.__qualname__, attempt + 1, wait)
                    time.sleep(wait)
            return {}
        return wrapper
    return decorator


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str) -> None:
        """Initialize Anthropic client with the given API key."""
        self._client = anthropic.Anthropic(api_key=api_key)

    @_llm_retry(max_attempts=3, delay=2.0)
    def complete_structured(
        self,
        prompt: str,
        tool: dict,
        system: str = "",
        max_tokens: int = 400,
        model_tier: str = "fast",
    ) -> dict:
        """Call Anthropic tool-use API and return the tool input dict."""
        try:
            kwargs = dict(
                model=_MODELS.get(model_tier, _MODELS["fast"]),
                max_tokens=max_tokens,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": prompt}],
            )
            if system:
                kwargs["system"] = system

            msg = self._client.messages.create(**kwargs)
            tool_block = next(b for b in msg.content if b.type == "tool_use")
            return tool_block.input
        except Exception as e:
            logger.warning("AnthropicProvider.complete_structured failed: %s", e)
            return {}
