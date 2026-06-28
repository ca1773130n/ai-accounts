"""Auto-detect existing CLI-logged-in config directories.

The user has likely already used the upstream CLIs (`claude`, `codex`,
`antigravity`, `opencode`) with one or more config directories — `~/.claude`,
`~/.claude-work`, `~/.codex-personal1`, etc. Re-doing the login flow in
our wizard for an account that's already authenticated is busywork.
This module:

  1. Globs each backend's per-kind home pattern (``~/.claude*``, ``~/.codex*``,
     etc.) for candidate directories.
  2. Runs a small CLI probe per directory (kind-specific, e.g. ``claude -p
     hello`` under ``CLAUDE_CONFIG_DIR=<dir>``) to verify the account is
     actually logged in.
  3. Returns a list the route layer can offer to the UI for one-click import.

Importing a discovered config is just an ordinary ``AccountService.create``
with ``config.config_path = <discovered_dir>`` — the rest of our backend
pipeline (validate, list_models, chat) already honours ``config_path`` to
pick up an existing CLI session without re-auth.

Notes
-----
* Probes are real prompt runs ("hello") and DO cost upstream tokens. They
  also take up to ``probe_timeout`` seconds each. Run them only on user
  intent, not automatically on every page load.
* Glob patterns intentionally exclude `~/.claude.json` (the global CLI
  config file, not a directory) by requiring the candidate to be a dir.
* The dedup logic in ``AccountService.create`` means importing the same
  directory twice updates the existing row rather than spawning a second.

Safety
------
Subprocess calls use ``asyncio.create_subprocess_exec`` (argv list, no
shell) so user-controlled inputs (config paths from glob) cannot inject
shell metacharacters. ``shell=True`` is never used.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# Glob pattern (relative to $HOME) per backend kind. Trailing `*` matches
# the bare dir AND any suffix (`.claude`, `.claude-work`, etc.).
_HOME_GLOB: dict[str, str] = {
    "claude": ".claude*",
    "codex": ".codex*",
    "antigravity": ".antigravity*",
    "opencode": ".opencode*",
}


def _probe_for(kind: str, config_dir: str) -> tuple[list[str], dict[str, str]]:
    """Build (argv, env_overrides) for the per-kind liveness probe.

    For most kinds the probe is a one-word non-interactive prompt — success
    means the CLI can reach its upstream API with the credentials in
    ``config_dir``. Codex uses ``codex login status`` instead: it's free,
    instant, and the old ``codex exec hello`` probe routinely blew the 12s
    probe_timeout (a real model call), false-negativing valid logins —
    which then downgraded already-imported backends READY → ERROR via the
    discover_existing() status sync. NOTE: ``codex login status`` exits 0
    even when logged out, so _run_probe inspects the status text for codex.
    """
    abs_dir = str(Path(config_dir).expanduser().resolve())
    if kind == "claude":
        return (["claude", "-p", "hello"], {"CLAUDE_CONFIG_DIR": abs_dir})
    if kind == "codex":
        return (["codex", "login", "status"], {"CODEX_HOME": abs_dir})
    if kind == "antigravity":
        return (["antigravity", "-p", "hello"], {"ANTIGRAVITY_HOME": abs_dir})
    if kind == "opencode":
        return (["opencode", "run", "hello"], {"OPENCODE_HOME": abs_dir})
    raise ValueError(f"no discovery probe configured for kind: {kind}")


@dataclass(frozen=True)
class DiscoveredConfig:
    kind: str
    path: str
    suggested_name: str
    is_logged_in: bool
    error: str | None = None
    # Set when this path is already represented by an existing backend
    # row — the UI hides the Import button and instead surfaces the
    # current backend status (which the service syncs to the probe
    # result before returning). None means "not yet imported".
    backend_id: str | None = None


async def _claude_keychain_quick_check(config_path: Path) -> bool | None:
    """Fast pre-check for Claude on macOS: ask the keychain directly
    whether ``config_path`` has a valid OAuth token.

    Returns:
        ``True``  — keychain has a non-empty ``claudeAiOauth.accessToken``
                    for this config_dir; caller can skip the subprocess
                    probe entirely.
        ``False`` — definitively not logged in via keychain.
        ``None``  — non-macOS or keychain dump unavailable; caller
                    should fall back to the subprocess probe.

    Why this exists: ``claude -p hello`` costs upstream tokens, takes
    up to ~12s, and is a false-negative magnet when the keychain has
    a duplicate item with the same service name (e.g. an orphan MCP
    plugin OAuth entry shadowing the real Claude account credential).
    A direct keychain read with proper account-scoped lookup costs
    nothing and handles duplicates correctly.
    """
    import sys as _sys
    if _sys.platform != "darwin":
        return None
    try:
        # Import inside the function so the discovery → claude-backend
        # dependency arrow stays one-way at module load.
        from ai_accounts_core.backends.claude import (
            claude_is_logged_in_via_macos_keychain,
        )
    except ImportError:
        return None
    try:
        ok = await claude_is_logged_in_via_macos_keychain(config_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("claude keychain quick-check raised: %r", exc)
        return None
    return True if ok else False


async def _run_probe(
    kind: str, config_path: Path, *, probe_timeout: float
) -> tuple[bool, str | None]:
    """Run the per-kind probe. Returns (ok, error_excerpt).

    Uses ``asyncio.create_subprocess_exec`` (argv list, no shell), so the
    config_path string cannot be used for shell injection.
    """
    # Claude on macOS: try the keychain quick-check first. A True
    # result skips the upstream API call entirely (cheap + reliable);
    # a False/None result still runs the subprocess probe as a
    # tie-breaker.
    if kind == "claude":
        quick = await _claude_keychain_quick_check(config_path)
        if quick is True:
            return True, None
    try:
        argv, env_overrides = _probe_for(kind, str(config_path))
    except ValueError as exc:
        return False, str(exc)
    cli_name = argv[0]
    if shutil.which(cli_name) is None:
        return False, f"{cli_name} CLI not installed"

    env = {**os.environ, **env_overrides}
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except OSError as os_err:
        return False, f"spawn failed: {os_err}"

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=probe_timeout)
    except TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return False, f"probe timed out after {probe_timeout}s"

    if proc.returncode == 0:
        if kind == "codex":
            # `codex login status` exits 0 even when logged OUT — inspect
            # the status text. Codex 0.121 prints to stdout, 0.128+ to
            # stderr; check both (mirrors backends/codex.py validate()).
            out_text = (stdout or b"").decode("utf-8", errors="replace").lower()
            err_text = (stderr or b"").decode("utf-8", errors="replace").lower()
            text = f"{out_text}\n{err_text}"
            if "logged in" in text and "not logged in" not in text:
                return True, None
            return False, "not logged in"
        return True, None
    err = (stderr or b"").decode("utf-8", errors="replace").strip()
    if not err:
        err = (stdout or b"").decode("utf-8", errors="replace").strip()
    excerpt = " ".join(err.split())[:200] if err else f"exit {proc.returncode}"
    return False, excerpt


def _suggested_name(kind: str, path: Path) -> str:
    """Friendly default display name for an imported config.

    ``~/.claude`` → "claude (default)"
    ``~/.claude-personal1`` → "personal1"
    ``~/.codex-codexfree`` → "codexfree"
    """
    name = path.name
    stripped = name[1:] if name.startswith(".") else name
    if stripped == kind:
        return f"{kind} (default)"
    prefix = f"{kind}-"
    if stripped.startswith(prefix):
        return stripped[len(prefix) :]
    return stripped


def _glob_candidates(kind: str) -> list[Path]:
    """Glob ~/.kind* for directories. Returns sorted, dedup'd paths."""
    pattern = _HOME_GLOB.get(kind)
    if pattern is None:
        return []
    home = Path.home()
    candidates = sorted(home.glob(pattern))
    return [p for p in candidates if p.is_dir()]


async def discover_for_kind(kind: str, *, probe_timeout: float = 12.0) -> list[DiscoveredConfig]:
    """Discover + probe all candidates for one backend kind in parallel."""
    candidates = _glob_candidates(kind)
    if not candidates:
        return []

    async def _one(path: Path) -> DiscoveredConfig:
        ok, err = await _run_probe(kind, path, probe_timeout=probe_timeout)
        return DiscoveredConfig(
            kind=kind,
            path=str(path),
            suggested_name=_suggested_name(kind, path),
            is_logged_in=ok,
            error=err,
        )

    return list(await asyncio.gather(*[_one(p) for p in candidates]))


async def discover_all(kinds: list[str], *, probe_timeout: float = 12.0) -> list[DiscoveredConfig]:
    """Run discovery across multiple kinds in parallel. Skips unknown kinds."""
    known = [k for k in kinds if k in _HOME_GLOB]
    if not known:
        return []
    per_kind = await asyncio.gather(
        *[discover_for_kind(k, probe_timeout=probe_timeout) for k in known]
    )
    flat: list[DiscoveredConfig] = []
    for batch in per_kind:
        flat.extend(batch)
    return flat
