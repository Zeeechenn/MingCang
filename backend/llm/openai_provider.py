import json
import logging
from backend.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_MODELS = {
    "fast":    "anthropic/claude-sonnet-4.6",
    "capable": "anthropic/claude-sonnet-4.6",
}


class OpenAIProvider(LLMProvider):
    """
    兼容 OpenAI API 的提供方（也适用于任何 OpenAI-compatible endpoint，
    例如 Azure OpenAI、DeepSeek、Moonshot、通义千问等）。
    base_url 留空时使用 OpenAI 官方地址。
    """

    def __init__(self, api_key: str, base_url: str = "") -> None:
        """Initialize OpenAI-compatible client with API key and optional base URL."""
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai 包未安装，运行：pip install openai")
        kwargs = {"api_key": api_key, "timeout": 30.0}
        if base_url:
            kwargs["base_url"] = base_url
            # OpenRouter 要求这两个 header 用于路由追踪
            kwargs["default_headers"] = {
                "HTTP-Referer": "https://github.com/stock-sage",
                "X-Title": "StockSage",
            }
        self._client = OpenAI(**kwargs)

    def complete_structured(
        self,
        prompt: str,
        tool: dict,
        system: str = "",
        max_tokens: int = 400,
        model_tier: str = "fast",
    ) -> dict:
        """Call OpenAI function-calling API and return the parsed arguments dict."""
        # Anthropic input_schema 与 OpenAI function parameters 使用相同的 JSON Schema 格式
        function_def = {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = self._client.chat.completions.create(
                model=_MODELS.get(model_tier, _MODELS["fast"]),
                max_tokens=max_tokens,
                tools=[{"type": "function", "function": function_def}],
                tool_choice={"type": "function", "function": {"name": tool["name"]}},
                messages=messages,
            )
            args = resp.choices[0].message.tool_calls[0].function.arguments
            return self._safe_json_loads(args)
        except Exception as e:
            logger.warning("OpenAIProvider.complete_structured failed: %s", e)
            return {}

    @staticmethod
    def _safe_json_loads(s: str) -> dict:
        """Parse JSON from function.arguments; repair truncated output by closing open braces."""
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            stripped = s.rstrip(', \n\r\t')
            open_braces = stripped.count('{') - stripped.count('}')
            open_brackets = stripped.count('[') - stripped.count(']')
            if open_braces > 0 or open_brackets > 0:
                repaired = stripped + ']' * max(0, open_brackets) + '}' * max(0, open_braces)
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass
            logger.warning("OpenAIProvider._safe_json_loads: could not repair JSON (len=%d)", len(s))
            return {}
