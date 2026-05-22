from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    payload = {
        "mcpServers": {
            "stock-sage": {
                "command": sys.executable,
                "args": ["-m", "backend.agent.mcp_server"],
                "cwd": str(root),
                "env": {
                    "PYTHONPATH": str(root),
                    "STOCKSAGE_AGENT_MODE": "local",
                },
            }
        }
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
