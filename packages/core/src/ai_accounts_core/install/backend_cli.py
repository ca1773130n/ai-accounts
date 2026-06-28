"""Per-backend CLI installer.

Each supported backend declares an install command. Hosts invoke via
``install_backend_cli(kind)`` which returns structured stdout/stderr and
an exit code, so the UI can display success/failure.
"""

from __future__ import annotations

import asyncio
import shutil

import msgspec


class InstallCommand(msgspec.Struct):
    """One install strategy for a backend CLI."""

    argv: list[str]
    display: str
    check_binary: str


_INSTALL_STRATEGIES: dict[str, list[InstallCommand]] = {
    "claude": [
        InstallCommand(
            argv=["npm", "install", "-g", "@anthropic-ai/claude-code"],
            display="npm install -g @anthropic-ai/claude-code",
            check_binary="claude",
        ),
    ],
    "codex": [
        InstallCommand(
            argv=["npm", "install", "-g", "@openai/codex"],
            display="npm install -g @openai/codex",
            check_binary="codex",
        ),
    ],
    # Antigravity (internal kind "antigravity") needs no terminal CLI — login is
    # handled via cliproxyapi's native Antigravity OAuth, so there's no
    # install strategy to register.
    "opencode": [
        InstallCommand(
            argv=["npm", "install", "-g", "opencode-ai"],
            display="npm install -g opencode-ai",
            check_binary="opencode",
        ),
    ],
    "goose": [
        InstallCommand(
            argv=[
                "bash",
                "-c",
                "curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | bash",
            ],
            display="curl -fsSL https://github.com/block/goose/.../download_cli.sh | bash",
            check_binary="goose",
        ),
    ],
    "aider": [
        InstallCommand(
            argv=["pipx", "install", "aider-chat"],
            display="pipx install aider-chat",
            check_binary="aider",
        ),
        InstallCommand(
            argv=["uv", "tool", "install", "aider-chat"],
            display="uv tool install aider-chat",
            check_binary="aider",
        ),
    ],
    "crush": [
        InstallCommand(
            argv=["npm", "install", "-g", "@charmland/crush"],
            display="npm install -g @charmland/crush",
            check_binary="crush",
        ),
    ],
}


class InstallResult(msgspec.Struct):
    kind: str
    success: bool
    display: str
    stdout: str
    stderr: str
    exit_code: int
    binary_path: str | None


async def install_backend_cli(kind: str) -> InstallResult:
    """Install a backend CLI.

    Tries each registered strategy in order and returns on first success.
    If no strategy works, returns the last failure's result.
    """
    strategies = _INSTALL_STRATEGIES.get(kind)
    if not strategies:
        raise ValueError(f"no install strategy registered for kind '{kind}'")

    last_result: InstallResult | None = None
    for strategy in strategies:
        try:
            proc = await asyncio.create_subprocess_exec(
                *strategy.argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            exit_code = proc.returncode or 0
        except (FileNotFoundError, OSError) as exc:
            # The installer command itself isn't available (e.g. pipx missing
            # while uv is present) — record the failure and try the next
            # strategy instead of raising before the fallback runs.
            last_result = InstallResult(
                kind=kind,
                success=False,
                display=strategy.display,
                stdout="",
                stderr=f"{type(exc).__name__}: {exc}",
                exit_code=127,
                binary_path=None,
            )
            continue
        binary_path = shutil.which(strategy.check_binary)
        success = exit_code == 0 and binary_path is not None

        last_result = InstallResult(
            kind=kind,
            success=success,
            display=strategy.display,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            exit_code=exit_code,
            binary_path=binary_path,
        )
        if success:
            return last_result

    assert last_result is not None
    return last_result


def get_install_strategies(kind: str) -> list[InstallCommand]:
    return list(_INSTALL_STRATEGIES.get(kind, []))
