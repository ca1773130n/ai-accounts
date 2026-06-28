"""Shared model-list fallbacks + cached-live persistence.

Three layers, in priority order at backend list_models() call sites:

1. Direct provider API (Anthropic /v1/models, OpenAI /v1/models, etc.) —
   authoritative, scoped to the stored credential.
2. CLIProxyAPI live /v1/models — used when an account is registered through
   cliproxy. cliproxy_list_models() writes successful responses to
   ``~/.ai-accounts/models_cache.json`` so subsequent offline calls keep
   working.
3. ``cached_live(provider)`` — last successful cliproxy snapshot.
4. ``static_fallback(provider)`` — version-pinned list shipped with the
   package, refreshed each release.

This module exists because the static lists were drifting per release — three
fixes in 2026-05 alone. Centralizing them here means one diff per upstream
mapping change instead of four.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ai_accounts_core.protocols.backend import Model


def cache_path() -> Path:
    """Where the cross-session model cache lives. Override with ``AI_ACCOUNTS_CACHE_DIR``."""
    root = os.environ.get("AI_ACCOUNTS_CACHE_DIR")
    if root:
        return Path(root) / "models_cache.json"
    return Path.home() / ".ai-accounts" / "models_cache.json"


def cached_live(provider: str) -> list[Model] | None:
    """Return the last successful cliproxy snapshot for ``provider``, or None.

    Never raises — missing/corrupt cache returns None so the caller falls
    through to the static set.
    """
    path = cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get(provider)
    if not isinstance(raw, list):
        return None
    out: list[Model] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        out.append(
            Model(
                id=mid,
                display_name=str(m.get("display_name") or mid),
                context_window=m.get("context_window")
                if isinstance(m.get("context_window"), int)
                else None,
            )
        )
    return out or None


def write_cache(provider: str, items: list[dict[str, Any]]) -> None:
    """Persist a successful cliproxy /v1/models response for ``provider``.

    Best-effort: any I/O error is swallowed (cache is a freshness optimization,
    never on the hot path).
    """
    if not items:
        return  # don't pollute cache with empty results
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            decoded = json.loads(path.read_text())
            if isinstance(decoded, dict):
                existing = decoded
        except (OSError, json.JSONDecodeError):
            existing = {}
    serialized = [
        {
            "id": item.get("id"),
            "display_name": item.get("display_name") or item.get("id"),
            "context_window": item.get("context_window"),
        }
        for item in items
        if isinstance(item, dict) and item.get("id")
    ]
    existing[provider] = serialized
    try:
        path.write_text(json.dumps(existing, separators=(",", ":")))
    except OSError:
        pass


# ── Static fallbacks (last resort) ────────────────────────────────────────
# Refreshed each release. Source of truth: cliproxyapi 6.8.30 provider
# mappings + the upstream CLI's `models list` output where available.
# Adding/removing a model? Touch only this file.

_STATIC_CLAUDE: tuple[Model, ...] = (
    Model(id="claude-opus-4-7", display_name="Claude Opus 4.7", context_window=1_000_000),
    Model(id="claude-opus-4-6", display_name="Claude Opus 4.6", context_window=1_000_000),
    Model(id="claude-opus-4-5-20251101", display_name="Claude Opus 4.5", context_window=200_000),
    Model(id="claude-sonnet-4-7", display_name="Claude Sonnet 4.7", context_window=1_000_000),
    Model(id="claude-sonnet-4-6", display_name="Claude Sonnet 4.6", context_window=1_000_000),
    Model(
        id="claude-sonnet-4-5-20250929", display_name="Claude Sonnet 4.5", context_window=1_000_000
    ),
    Model(id="claude-haiku-4-5-20251001", display_name="Claude Haiku 4.5", context_window=200_000),
)

_STATIC_CODEX: tuple[Model, ...] = (
    Model(id="gpt-5.5", display_name="GPT-5.5", context_window=400_000),
    Model(id="gpt-5.3-codex", display_name="GPT-5.3 Codex", context_window=400_000),
    Model(id="gpt-5.3-codex-spark", display_name="GPT-5.3 Codex Spark", context_window=400_000),
    Model(id="gpt-5.2-codex", display_name="GPT-5.2 Codex", context_window=400_000),
    Model(id="gpt-5.1-codex-max", display_name="GPT-5.1 Codex Max", context_window=400_000),
    Model(id="gpt-5.1-codex-mini", display_name="GPT-5.1 Codex Mini", context_window=400_000),
    Model(id="gpt-5-codex", display_name="GPT-5 Codex", context_window=400_000),
    Model(id="gpt-5-codex-mini", display_name="GPT-5 Codex Mini", context_window=400_000),
    Model(id="gpt-5.2", display_name="GPT-5.2", context_window=400_000),
    Model(id="gpt-5", display_name="GPT-5", context_window=400_000),
)

# antigravity and opencode have no shipped static set — both rely on live discovery
# (Google AI Studio / OpenRouter) which is reliable while the credential is
# valid. Empty fallback is correct: an unreachable upstream yields an empty
# dropdown, which is preferable to advertising stale ids.

_STATIC: dict[str, tuple[Model, ...]] = {
    "claude": _STATIC_CLAUDE,
    "codex": _STATIC_CODEX,
    "antigravity": (),
    "opencode": (),
    "openrouter": (),
    "openai_compat": (),
    "kimi": (),
    "deepseek": (
        Model(id="deepseek-v4-flash", display_name="DeepSeek V4 Flash"),
        Model(id="deepseek-v4-pro", display_name="DeepSeek V4 Pro"),
    ),
    "qwen": (
        Model(id="qwen3-coder-plus", display_name="Qwen3 Coder Plus"),
        Model(id="qwen3-coder-flash", display_name="Qwen3 Coder Flash"),
    ),
}


def static_fallback(provider: str) -> list[Model]:
    """Return a fresh list copy of the shipped static set for ``provider``."""
    return list(_STATIC.get(provider, ()))


def fallback(provider: str) -> list[Model]:
    """Resolve the offline fallback for ``provider``: cached-live → static.

    Centralizes the "no live source available" branch. Backends call this
    after their direct-API and cliproxy paths return empty.
    """
    cached = cached_live(provider)
    if cached:
        return cached
    return static_fallback(provider)
