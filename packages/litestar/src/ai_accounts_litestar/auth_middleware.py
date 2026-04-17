"""Auth middleware that enforces ``config.auth`` on every request.

Without this middleware the ``AuthProtocol`` provider configured on
``AiAccountsConfig`` would never be consulted — production code only
*checked* that ``NoAuth`` was not configured, but no guard was wired into
request handling, so every endpoint was effectively unauthenticated.

The middleware:

* Exempts ``/health`` and the auto-generated OpenAPI routes (``/schema``),
  so liveness probes and spec fetchers still work before auth is known.
* Builds a protocol-level ``RequestContext`` from the ASGI scope and calls
  ``auth.authenticate(...)``.
* On ``None`` principal, returns a compact JSON 401. On success, stashes
  the principal in ``scope["state"]["principal"]`` for handlers that care.

When ``auth`` is ``None`` on the config (development convenience) the app
factory simply doesn't install this middleware — the production-mode
guard refuses to start with ``auth=None``, so this can only skip auth in
development environments.
"""

from __future__ import annotations

import json
import re
from typing import Any

from litestar.middleware import AbstractMiddleware
from litestar.types import ASGIApp, Receive, Scope, Send

from ai_accounts_core.protocols.auth import AuthProtocol, RequestContext

_EXEMPT_PATTERNS = (
    re.compile(r"^/health$"),
    re.compile(r"^/schema(/|$)"),
)


def _is_exempt(path: str) -> bool:
    return any(pat.match(path) for pat in _EXEMPT_PATTERNS)


def _headers_from_scope(scope: Scope) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", []) or []:
        try:
            name = raw_name.decode("latin-1").lower()
            value = raw_value.decode("latin-1")
        except UnicodeDecodeError:
            continue
        # Duplicate header names are rare in practice for the ones auth
        # providers care about; last-wins is fine and matches Litestar's
        # own headers proxy behavior on attribute access.
        out[name] = value
    return out


def _query_from_scope(scope: Scope) -> dict[str, str]:
    raw = scope.get("query_string") or b""
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.decode("latin-1").split("&"):
        if not pair:
            continue
        if "=" in pair:
            k, v = pair.split("=", 1)
        else:
            k, v = pair, ""
        out[k] = v
    return out


async def _send_json_response(
    send: Send, *, status: int, body: dict[str, Any]
) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload, "more_body": False})


class AuthMiddleware(AbstractMiddleware):
    scopes = {"http", "websocket"}

    def __init__(self, app: ASGIApp, *, auth_provider: AuthProtocol) -> None:
        super().__init__(app)
        self._auth = auth_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "") or ""
        if _is_exempt(path):
            await self.app(scope, receive, send)
            return

        method: str = scope.get("method", "GET") or "GET"
        headers = _headers_from_scope(scope)
        query = _query_from_scope(scope)

        ctx = RequestContext(
            method=method,
            path=path,
            headers=headers,
            query=query,
        )

        principal = await self._auth.authenticate(ctx)
        if principal is None:
            if scope["type"] == "websocket":
                # WebSocket: close with 4401 (policy violation, app-level)
                await send({"type": "websocket.close", "code": 4401})
                return
            await _send_json_response(
                send,
                status=401,
                body={"error": {"code": "unauthorized", "message": "authentication required"}},
            )
            return

        # Expose the principal to downstream handlers.
        state = scope.setdefault("state", {})
        state["principal"] = principal
        await self.app(scope, receive, send)
