from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_native_pi_extension_registers_expected_tools():
    repo = Path(__file__).resolve().parents[1]
    extension = repo / ".pi" / "extensions" / "mingcang.ts"

    text = extension.read_text(encoding="utf-8")

    for name in (
        "mingcang_health",
        "mingcang_project_context",
        "mingcang_stock_context",
        "mingcang_memory_snapshot",
        "mingcang_action_dry_run",
        "mingcang_action_confirm",
    ):
        assert f'"{name}"' in text
    assert "stock" + "sage" not in text.lower()
    assert "stock" + "_sage" not in text
    assert "STOCK" + "SAGE" not in text
    assert "pi.registerTool" in text
    assert "backend.agent.cli" in text


def test_mingcang_launcher_exposes_trading_rhythm_commands_only():
    repo = Path(__file__).resolve().parents[1]
    launcher = repo / "scripts" / "mingcang_launcher.sh"

    text = launcher.read_text(encoding="utf-8")

    assert "premarket|intraday|postmarket" in text
    assert 'backend.agent.cli "$command_name" --pretty "$@"' in text
    assert "mingcang premarket" in text
    assert "mingcang intraday" in text
    assert "mingcang postmarket" in text
    assert not (repo / "scripts" / ("stock" + "sage_launcher.sh")).exists()
    assert "stock" + "sage" not in text.lower()
    assert "STOCK" + "SAGE" not in text


def test_agent_run_does_not_bulk_export_dotenv_secrets(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_pi = fake_bin / "pi"
    fake_pi.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'profile=%s\\n' \"$MINGCANG_PI_PROFILE\"\n"
        "printf 'anthropic=%s\\n' \"${ANTHROPIC_API_KEY-unset}\"\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)

    env = {
        "PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin",
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", "scripts/agent_run.sh", "research"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "profile=research" in result.stdout
    assert "anthropic=unset" in result.stdout
