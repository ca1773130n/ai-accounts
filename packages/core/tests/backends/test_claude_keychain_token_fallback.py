"""Tests for ClaudeBackend keychain / .credentials.json OAuth-token fallback (v0.7.11).

The v0.7.10 ``_list_models_via_provider_api`` returned ``None`` whenever the
stored credential was empty — but cli_browser logins always have empty
credentials, since the OAuth bearer is held by the upstream Claude CLI
(macOS keychain or ``<CLAUDE_CONFIG_DIR>/.credentials.json``). v0.7.11 adds
two fallback helpers that read those locations directly so /v1/models
discovery actually fires for subscription accounts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from ai_accounts_core.backends.claude import ClaudeBackend

_FAKE_DUMP_KEYCHAIN_OUTPUT = """\
keychain: "/Users/u/Library/Keychains/login.keychain-db"
class: "genp"
attributes:
    0x00000007 <blob>="Claude Safe Storage"
    "acct"<blob>="Claude Key"
    "svce"<blob>="Claude Safe Storage"
keychain: "/Users/u/Library/Keychains/login.keychain-db"
class: "genp"
attributes:
    "svce"<blob>="Claude Code-credentials-abc123def456"
    "acct"<blob>="user@example.com"
keychain: "/Users/u/Library/Keychains/login.keychain-db"
class: "genp"
attributes:
    "svce"<blob>="com.apple.assistant"
"""

_FAKE_OAUTH_BLOB = json.dumps(
    {
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat-FAKE-TOKEN-VALUE",
            "refreshToken": "sk-ant-ort-FAKE",
            "expiresAt": 9_999_999_999,
            "scopes": ["user:inference"],
            "subscriptionType": "max",
            "rateLimitTier": "default",
        }
    }
)


def _fake_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    """Mimic ``subprocess.CompletedProcess`` enough for our helpers."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.mark.asyncio
async def test_keychain_extracts_oauth_token_from_credentials_entry(monkeypatch):
    """dump-keychain lists a ``Claude Code-credentials-*`` entry → its
    ``-w`` JSON blob is parsed and ``accessToken`` returned."""
    if sys.platform != "darwin":
        pytest.skip("macOS keychain path only")

    calls: list[list[str]] = []

    def _fake_run(argv, *args, **kwargs):
        calls.append(list(argv))
        if argv[:2] == ["security", "dump-keychain"]:
            return _fake_completed(0, stdout=_FAKE_DUMP_KEYCHAIN_OUTPUT)
        if argv[:2] == ["security", "find-generic-password"] and "-w" in argv:
            assert "Claude Code-credentials-abc123def456" in argv
            return _fake_completed(0, stdout=_FAKE_OAUTH_BLOB + "\n")
        return _fake_completed(1)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    backend = ClaudeBackend()
    token = await backend._try_macos_keychain_oauth_token()
    assert token == "sk-ant-oat-FAKE-TOKEN-VALUE"
    # Sanity-check the call shape — we asked for the right service with -w.
    assert any(
        "find-generic-password" in c and "Claude Code-credentials-abc123def456" in c for c in calls
    )


@pytest.mark.asyncio
async def test_keychain_returns_none_when_no_credentials_entries(monkeypatch):
    """dump-keychain succeeds but lists no Claude Code-credentials-* services."""
    if sys.platform != "darwin":
        pytest.skip("macOS keychain path only")

    no_match = """\
attributes:
    "svce"<blob>="Claude Safe Storage"
    "svce"<blob>="com.apple.assistant"
"""

    def _fake_run(argv, *args, **kwargs):
        if argv[:2] == ["security", "dump-keychain"]:
            return _fake_completed(0, stdout=no_match)
        # No find-generic-password should be invoked.
        raise AssertionError(f"unexpected subprocess call: {argv}")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    backend = ClaudeBackend()
    assert await backend._try_macos_keychain_oauth_token() is None


@pytest.mark.asyncio
async def test_keychain_skips_invalid_json_entry(monkeypatch):
    """A corrupted entry's JSON parse failure must not abort the sweep —
    a later entry with a valid blob still wins."""
    if sys.platform != "darwin":
        pytest.skip("macOS keychain path only")

    dump = """\
attributes:
    "svce"<blob>="Claude Code-credentials-bad"
attributes:
    "svce"<blob>="Claude Code-credentials-good"
"""

    def _fake_run(argv, *args, **kwargs):
        if argv[:2] == ["security", "dump-keychain"]:
            return _fake_completed(0, stdout=dump)
        if argv[:2] == ["security", "find-generic-password"]:
            if "Claude Code-credentials-bad" in argv:
                return _fake_completed(0, stdout="not-json{{{")
            if "Claude Code-credentials-good" in argv:
                return _fake_completed(0, stdout=_FAKE_OAUTH_BLOB)
        return _fake_completed(1)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    backend = ClaudeBackend()
    token = await backend._try_macos_keychain_oauth_token()
    assert token == "sk-ant-oat-FAKE-TOKEN-VALUE"


@pytest.mark.asyncio
async def test_keychain_returns_none_when_dump_keychain_fails(monkeypatch):
    """dump-keychain non-zero exit → bail without calling find-generic-password."""
    if sys.platform != "darwin":
        pytest.skip("macOS keychain path only")

    def _fake_run(argv, *args, **kwargs):
        if argv[:2] == ["security", "dump-keychain"]:
            return _fake_completed(1, stderr="permission denied")
        raise AssertionError(f"unexpected call after failed dump: {argv}")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    backend = ClaudeBackend()
    assert await backend._try_macos_keychain_oauth_token() is None


@pytest.mark.asyncio
async def test_credentials_file_extracts_token(tmp_path):
    """``<isolation_dir>/.credentials.json`` with the standard claudeAiOauth
    shape → accessToken returned."""
    creds = tmp_path / ".credentials.json"
    creds.write_text(_FAKE_OAUTH_BLOB)

    backend = ClaudeBackend()
    token = await backend._try_credentials_file_oauth_token(tmp_path)
    assert token == "sk-ant-oat-FAKE-TOKEN-VALUE"


@pytest.mark.asyncio
async def test_credentials_file_missing_returns_none(tmp_path):
    """No file at all → None (covers Linux pre-login + fresh isolation_dir)."""
    backend = ClaudeBackend()
    token = await backend._try_credentials_file_oauth_token(tmp_path)
    assert token is None


@pytest.mark.asyncio
async def test_credentials_file_malformed_json_returns_none(tmp_path):
    """File exists but isn't JSON → None, never raises."""
    (tmp_path / ".credentials.json").write_text("not valid json {{{")
    backend = ClaudeBackend()
    assert await backend._try_credentials_file_oauth_token(tmp_path) is None


@pytest.mark.asyncio
async def test_credentials_file_missing_oauth_key_returns_none(tmp_path):
    """JSON parses but lacks the claudeAiOauth wrapper → None."""
    (tmp_path / ".credentials.json").write_text(json.dumps({"other": "shape"}))
    backend = ClaudeBackend()
    assert await backend._try_credentials_file_oauth_token(tmp_path) is None


@pytest.mark.asyncio
async def test_credentials_file_empty_token_returns_none(tmp_path):
    """The wrapper exists but accessToken is the empty string → None."""
    (tmp_path / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": ""}}))
    backend = ClaudeBackend()
    assert await backend._try_credentials_file_oauth_token(tmp_path) is None


@pytest.mark.asyncio
async def test_list_models_via_provider_api_uses_credentials_file_when_credential_empty(
    tmp_path, httpx_mock, monkeypatch
):
    """End-to-end: empty credential + valid .credentials.json → /v1/models is
    called with the OAuth token from the file (Bearer + oauth-2025-04-20).

    The keychain helper is stubbed to None so the test exercises the
    file-fallback branch even on macOS hosts where the developer keychain
    might happen to contain a real Claude Code-credentials-* entry.
    """

    async def _no_keychain(self):
        return None

    monkeypatch.setattr(ClaudeBackend, "_try_macos_keychain_oauth_token", _no_keychain)
    (tmp_path / ".credentials.json").write_text(_FAKE_OAUTH_BLOB)
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/models",
        match_headers={
            "Authorization": "Bearer sk-ant-oat-FAKE-TOKEN-VALUE",
            "anthropic-beta": "oauth-2025-04-20",
        },
        json={
            "data": [
                {"type": "model", "id": "claude-opus-4-7", "display_name": "Claude Opus 4.7"},
            ]
        },
    )
    backend = ClaudeBackend()
    models = await backend._list_models_via_provider_api(b"", tmp_path)
    assert models is not None
    assert [m.id for m in models] == ["claude-opus-4-7"]
