"""Cached-live model-list persistence.

Three layers, in priority order at backend list_models() call sites:

1. Direct provider API (Anthropic /v1/models, OpenAI /v1/models, etc.) —
   authoritative, scoped to the stored credential.
2. CLIProxyAPI live /v1/models — used when an account is registered through
   cliproxy. cliproxy_list_models() writes successful responses to
   ``~/.ai-accounts/models_cache.json`` so subsequent offline calls keep
   working.
3. ``cached_live(provider)`` — last successful cliproxy snapshot.

There is deliberately no fourth layer. This module used to ship curated
per-provider "static fallback" lists, and they were wrong in every direction:
they advertised ids the provider had retired (a 404 on select) and omitted the
current default. Providers ship models faster than we ship releases, so the
list was stale by construction — four drift fixes across 0.3.9/0.3.10/0.3.12
and 0.5.0, none of which a curated list could have prevented.

An unreachable upstream now yields an empty dropdown, which is what the
antigravity/opencode/openrouter/kimi backends already did. Empty is honest;
a stale id looks like a working choice and isn't.
"""

from __future__ import annotations

import contextlib
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

    Never raises — a missing/corrupt cache returns None, which the caller
    treats as "no models known offline".
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
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(existing, separators=(",", ":")))


def fallback(provider: str) -> list[Model]:
    """Resolve the offline model list for ``provider``: the last cliproxy
    snapshot, else empty.

    Centralizes the "no live source available" branch. Backends call this after
    their direct-API and cliproxy paths return empty. Returning ``[]`` is a
    valid, expected outcome — see the module docstring.
    """
    return cached_live(provider) or []
