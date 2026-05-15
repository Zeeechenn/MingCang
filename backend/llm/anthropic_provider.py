import logging
import anthropic
from backend.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_MODELS = {
    "fast":    "claude-sonnet-4-6",
    "capable": "claude-sonnet-4-6",
}


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str) -> None:
        """Initialize Anthropic client with the given API key."""
        self._client = anthropic.Anthropic(api_key=api_key)

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
