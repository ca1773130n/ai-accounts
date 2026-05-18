"""v0.7.12: codex local models_cache.json discovery tests."""

from __future__ import annotations

import json
from pathlib import Path

from ai_accounts_core.backends.codex import CodexBackend


def _write_cache(path: Path, models: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "fetched_at": "2026-05-09T12:00:00Z",
                "etag": "abc",
                "client_version": "0.130.0",
                "models": models,
            }
        )
    )


def test_reads_slugs_from_isolation_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex"))
    monkeypatch.setenv("HOME", str(tmp_path / "no-home"))
    cache = tmp_path / "models_cache.json"
    _write_cache(
        cache,
        [
            {"slug": "gpt-5.5", "display_name": "GPT-5.5", "visibility": "list"},
            {"slug": "gpt-5.4", "display_name": "GPT-5.4", "visibility": "list"},
        ],
    )
    out = CodexBackend()._list_models_from_codex_cache(tmp_path)
    assert out is not None
    ids = [m.id for m in out]
    assert ids == ["gpt-5.5", "gpt-5.4"]


def test_skips_hidden_models(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex"))
    monkeypatch.setenv("HOME", str(tmp_path / "no-home"))
    cache = tmp_path / "models_cache.json"
    _write_cache(
        cache,
        [
            {"slug": "gpt-5.5", "visibility": "list"},
            {"slug": "internal-debug", "visibility": "hidden"},
            {"slug": "gpt-5.4", "visibility": "list"},
        ],
    )
    out = CodexBackend()._list_models_from_codex_cache(tmp_path)
    assert [m.id for m in out] == ["gpt-5.5", "gpt-5.4"]


def test_returns_none_when_cache_missing(tmp_path, monkeypatch):
    # Point CODEX_HOME and HOME at empty dirs so no fallback path resolves.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex"))
    monkeypatch.setenv("HOME", str(tmp_path / "no-home"))
    out = CodexBackend()._list_models_from_codex_cache(tmp_path / "isolated")
    assert out is None


def test_returns_none_on_corrupt_json(tmp_path, monkeypatch):
    # Isolate from the real ~/.codex cache that exists on dev machines.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex"))
    monkeypatch.setenv("HOME", str(tmp_path / "no-home"))
    cache = tmp_path / "models_cache.json"
    cache.write_text("{ not json")
    out = CodexBackend()._list_models_from_codex_cache(tmp_path)
    assert out is None


def test_dedupes_repeated_slugs(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex"))
    monkeypatch.setenv("HOME", str(tmp_path / "no-home"))
    cache = tmp_path / "models_cache.json"
    _write_cache(
        cache,
        [
            {"slug": "gpt-5.5", "display_name": "GPT-5.5", "visibility": "list"},
            {"slug": "gpt-5.5", "display_name": "Duplicate", "visibility": "list"},
            {"slug": "gpt-5.4", "visibility": "list"},
        ],
    )
    out = CodexBackend()._list_models_from_codex_cache(tmp_path)
    assert [m.id for m in out] == ["gpt-5.5", "gpt-5.4"]


def test_falls_back_to_codex_home(tmp_path, monkeypatch):
    home_cache = tmp_path / "codex-home" / "models_cache.json"
    _write_cache(
        home_cache,
        [
            {"slug": "gpt-5.5", "visibility": "list"},
        ],
    )
    monkeypatch.setenv("CODEX_HOME", str(home_cache.parent))
    out = CodexBackend()._list_models_from_codex_cache(tmp_path / "no-iso")
    assert out is not None
    assert [m.id for m in out] == ["gpt-5.5"]
