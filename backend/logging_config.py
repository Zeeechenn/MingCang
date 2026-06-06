"""中心化结构化日志配置。

用 structlog 包裹标准库 logging：通过 ProcessorFormatter 把标准库的
``logging.getLogger(__name__)`` 产生的日志记录桥接进 structlog 的处理链，
因此项目中现有的 56 处裸 ``logging.getLogger`` 调用无需改动即可自动获得
结构化输出。

渲染方式：开发环境采用 structlog 的 ConsoleRenderer（彩色 key=value 可读渲染），
便于本地直接阅读。如需切换为 JSON（生产/采集场景），把 ConsoleRenderer
替换为 ``structlog.processors.JSONRenderer()`` 即可。
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """配置 structlog + 标准库 logging 桥接。

    - 标准库 ``logging.getLogger(...)`` 的输出经 ProcessorFormatter 进入
      structlog 处理链，因此无需改动既有 getLogger 调用。
    - ``level`` 默认 "INFO"，调用方应传入 ``settings.log_level`` 以尊重配置。
    """
    log_level = getattr(logging, str(level).upper(), logging.INFO)

    # structlog 与标准库共享的预处理器：补充时间戳、日志级别、logger 名等。
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # structlog 自身的 logger 配置：把事件交给 ProcessorFormatter 做最终渲染，
    # 从而与标准库日志走同一条渲染管线。
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )

    # ProcessorFormatter：对来自标准库 logging 的记录（foreign records）先跑
    # shared_processors，再用 ConsoleRenderer 做 dev 下可读的 key=value 渲染。
    # 切 JSON：将 processor 改为 structlog.processors.JSONRenderer()。
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(),
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # 重置 handler，避免重复调用 configure_logging 时叠加多个 handler。
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
