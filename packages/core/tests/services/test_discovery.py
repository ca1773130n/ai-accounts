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
    "kind,expected_cli,expected_env_key",
    [
        ("claude", "claude", "CLAUDE_CONFIG_DIR"),
        ("codex", "codex", "CODEX_HOME"),
        ("gemini", "gemini", "GEMINI_CLI_HOME"),
        ("opencode", "opencode", "OPENCODE_HOME"),
    ],
)
def test_probe_for_shape(kind, expected_cli, expected_env_key, tmp_path):
    argv, env = _probe_for(kind, str(tmp_path))
    assert argv[0] == expected_cli
    assert "hello" in argv  # all four probes send a "hello" prompt
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

