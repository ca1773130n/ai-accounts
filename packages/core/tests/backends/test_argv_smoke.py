"""argv-smoke regression test.

For every CLI argv the backend wrappers invoke at runtime, verify that the
subcommand actually exists in the installed CLI version. This catches the
class of bug that hit `codex auth status` (didn't exist), `codex auth
--browser` (didn't exist), `gemini auth login --device` (didn't exist),
`gemini models list --json` (didn't exist), `opencode auth check` (didn't
exist), and `claude auth status` (didn't exist).

Tests are SKIPPED (not failed) if the CLI is not on PATH, so CI machines
without all four CLIs installed still pass.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

# (cli_name, argv) — argv is a list of args appended after the binary path.
# Each line is a real subcommand the wrappers shell out to. `--help` is added
# so we never trigger an interactive flow.
ARGV_CASES = [
    # claude — version smoke (claude has no scriptable auth status command;
    # validate is now file-based so there's no subcommand to probe).
    ("claude", ["--version"]),
    # codex — login flow + status check (codex 0.121+).
    ("codex", ["login", "--help"]),
    ("codex", ["login", "status", "--help"]),
    # gemini — version smoke (api_key flow doesn't shell out).
    ("gemini", ["--version"]),
    # opencode — providers list + login (opencode 0.x).
    ("opencode", ["providers", "list", "--help"]),
    ("opencode", ["providers", "login", "--help"]),
]


@pytest.mark.parametrize("cli, argv", ARGV_CASES)
def test_cli_subcommand_exists(cli: str, argv: list[str]) -> None:
    path = shutil.which(cli)
    if path is None:
        pytest.skip(f"{cli} not on PATH")
    full = [path, *argv]
    proc = subprocess.run(full, capture_output=True, timeout=10)
    assert proc.returncode == 0, (
        f"{' '.join(full)} returned rc={proc.returncode} — subcommand drift!\n"
        f"stdout: {proc.stdout.decode(errors='replace')[:200]}\n"
        f"stderr: {proc.stderr.decode(errors='replace')[:200]}"
    )
