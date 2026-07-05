import functools
import logging
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class LLMFatalResult(Exception):
    """不可重试的错误（鉴权失败/请求非法等），携带最终结果直接返回，跳过退避重试。"""
    def __init__(self, result: dict) -> None:
        self.result = result


def llm_retry(max_attempts: int = 3, delay: float = 2.0):
    """LLM 调用退避重试：空结果才重试；LLMFatalResult 直接返回其 result 不重试。"""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    result = fn(*args, **kwargs)
                except LLMFatalResult as e:
                    return e.result
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


class LLMProvider(ABC):
    """
    统一 LLM 接口。
    所有调用方只依赖此接口，不直接导入具体 SDK。
    """

    @abstractmethod
    def complete_structured(
        self,
        prompt: str,
        tool: dict,
        system: str = "",
        max_tokens: int = 400,
        model_tier: str = "fast",
    ) -> dict:
        """
        发送 prompt，强制返回符合 tool['input_schema'] 的结构化 dict。
        失败时返回空 dict {}。

        tool 格式与 Anthropic tool_use 定义完全一致：
          {"name": str, "description": str, "input_schema": {JSON Schema}}

        model_tier:
          "fast"    → 低延迟低价格（Haiku / gpt-4o-mini）
          "capable" → 高能力（Sonnet / gpt-4o）
        """
