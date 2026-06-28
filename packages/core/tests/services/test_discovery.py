"""Unit tests for services.discovery — pure-logic bits (glob, name munging,
probe builders, error paths). Live probe runs are exercised indirectly via
the route's smoke test; here we cover the deterministic surface.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from ai_accounts_core.services.discovery import (
    _glob_candidates,
    _probe_for,
    _run_probe,
    _suggested_name,
    discover_for_kind,
)

# ── _suggested_name ─────────────────────────────────────────────────────


def test_suggested_name_bare_default():
    assert _suggested_name("claude", Path("/home/u/.claude")) == "claude (default)"


def test_suggested_name_dash_suffix():
    assert _suggested_name("claude", Path("/home/u/.claude-personal1")) == "personal1"


def test_suggested_name_dash_suffix_codex():
    assert _suggested_name("codex", Path("/home/u/.codex-codexfree")) == "codexfree"


def test_suggested_name_underscore_keeps_full_name():
    # Underscore suffix (.codex_old) doesn't match the "-" prefix rule; keep
    # the whole stem so the user can tell it apart from siblings.
    assert _suggested_name("codex", Path("/home/u/.codex_old")) == "codex_old"


def test_suggested_name_unrelated_dir():
    # Edge: globbed path that doesn't match the kind prefix — keep stem as-is.
    assert _suggested_name("claude", Path("/home/u/.something")) == "something"


# ── _probe_for ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kind,expected_argv_prefix,expected_env_key",
    [
        ("claude", ["claude", "-p", "hello"], "CLAUDE_CONFIG_DIR"),
        # codex: `login status` — free and fast. The old `codex exec hello`
        # probe cost tokens and routinely blew the 12s probe_timeout,
        # false-negativing a perfectly valid login.
        ("codex", ["codex", "login", "status"], "CODEX_HOME"),
        ("antigravity", ["antigravity", "-p", "hello"], "ANTIGRAVITY_HOME"),
        ("opencode", ["opencode", "run", "hello"], "OPENCODE_HOME"),
    ],
)
def test_probe_for_shape(kind, expected_argv_prefix, expected_env_key, tmp_path):
    argv, env = _probe_for(kind, str(tmp_path))
    assert argv == expected_argv_prefix
    assert env.get(expected_env_key) == str(tmp_path.resolve())


def test_probe_for_unknown_kind_raises():
    with pytest.raises(ValueError, match="no discovery probe"):
        _probe_for("notreal", "/tmp/x")


def test_probe_for_resolves_relative_path(tmp_path, monkeypatch):
    # The CLI subprocess inherits our cwd, so the env var MUST be absolute
    # (relative would resolve against the child's cwd and double the path).
    monkeypatch.chdir(tmp_path)
    _argv, env = _probe_for("claude", ".claude-rel")
    assert Path(env["CLAUDE_CONFIG_DIR"]).is_absolute()


# ── _glob_candidates ────────────────────────────────────────────────────


def test_glob_finds_only_directories(tmp_path, monkeypatch):
    # Build a fake $HOME with mix of dirs and files matching the pattern.
    fake_home = tmp_path
    (fake_home / ".claude").mkdir()
    (fake_home / ".claude-work").mkdir()
    (fake_home / ".claude.json").write_text("{}")  # file — must be excluded
    (fake_home / ".unrelated").mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    paths = _glob_candidates("claude")
    names = [p.name for p in paths]
    assert names == [".claude", ".claude-work"]  # sorted, files excluded
    assert ".claude.json" not in names
    assert ".unrelated" not in names


def test_glob_unknown_kind_returns_empty():
    assert _glob_candidates("notreal") == []


# ── discover_for_kind ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discover_for_kind_no_candidates_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert await discover_for_kind("claude", probe_timeout=0.1) == []


@pytest.mark.asyncio
async def test_discover_for_kind_probes_each_candidate(tmp_path, monkeypatch):
    """All globbed dirs get probed in parallel; result preserves kind+path."""
    fake_home = tmp_path
    (fake_home / ".claude").mkdir()
    (fake_home / ".claude-work").mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    # Stub _run_probe so we don't actually shell out to claude.
    async def fake_probe(kind, path, *, probe_timeout):
        return (path.name == ".claude", None if path.name == ".claude" else "stub fail")

    with patch(
        "ai_accounts_core.services.discovery._run_probe", new=AsyncMock(side_effect=fake_probe)
    ):
        items = await discover_for_kind("claude", probe_timeout=1.0)

    paths = sorted([(i.path.endswith(".claude"), i.is_logged_in, i.error) for i in items])
    # Sorted by tuple — bool order doesn't matter, just confirm both surfaced.
    assert len(items) == 2
    ok_items = [i for i in items if i.is_logged_in]
    fail_items = [i for i in items if not i.is_logged_in]
    assert len(ok_items) == 1
    assert ok_items[0].path.endswith(".claude")
    assert ok_items[0].error is None
    assert len(fail_items) == 1
    assert fail_items[0].path.endswith(".claude-work")
    assert fail_items[0].error == "stub fail"


# ── _run_probe: codex text inspection ───────────────────────────────────
# `codex login status` exits 0 even when logged OUT, so rc alone is not
# evidence of auth — the runner must inspect the status text (and check
# BOTH streams: codex 0.121 prints to stdout, 0.128+ to stderr).


def _fake_proc(rc: int, stdout: bytes = b"", stderr: bytes = b""):
    proc = AsyncMock()
    proc.returncode = rc
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


@pytest.mark.asyncio
async def test_run_probe_codex_rc0_but_not_logged_in(tmp_path, monkeypatch):
    import shutil as _shutil

    monkeypatch.setattr(_shutil, "which", lambda name: f"/usr/bin/{name}")
    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_fake_proc(0, stdout=b"Not logged in\n")),
    ):
        ok, err = await _run_probe("codex", tmp_path, probe_timeout=1.0)
    assert ok is False
    assert "not logged in" in (err or "").lower()


@pytest.mark.asyncio
async def test_run_probe_codex_logged_in_via_stderr(tmp_path, monkeypatch):
    import shutil as _shutil

    monkeypatch.setattr(_shutil, "which", lambda name: f"/usr/bin/{name}")
    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_fake_proc(0, stderr=b"Logged in using ChatGPT\n")),
    ):
        ok, err = await _run_probe("codex", tmp_path, probe_timeout=1.0)
    assert ok is True
    assert err is None
