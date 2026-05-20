"""Standalone scheduler worker entry for launchd/systemd/supervisor."""
from __future__ import annotations

import logging
import signal
import time

from backend.scheduler import start, stop

logger = logging.getLogger(__name__)
_running = True


def _handle_stop(signum, frame) -> None:
    global _running
    _running = False
    logger.info("scheduler worker received signal %s", signum)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    start()
    try:
        while _running:
            time.sleep(1)
    finally:
        stop()


if __name__ == "__main__":
    main()
