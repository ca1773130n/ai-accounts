"""Shared CLIProxyAPI chat routing for CLI-browser-authenticated accounts."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent

logger = logging.getLogger(__name__)


async def _chat_via_cliproxy(request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
    """Route chat through CLIProxyAPI's OpenAI-compatible endpoint.

    Used when credential is empty (CLI-browser/OAuth login) — the CLI
    manages its own credentials and CLIProxyAPI exposes them via
    an OpenAI-compatible API.
    """
    from ai_accounts_core.cliproxy import detect_cliproxy

    try:
        proxy = detect_cliproxy()
    except Exception as exc:
        logger.warning("detect_cliproxy failed: %s", exc)
        proxy = None

    if proxy is None:
        yield ChatStreamEvent(
            kind="error",
            payload="CLIProxyAPI not running — install and start cliproxyapi, or use an API key",
        )
        return

    base_url, api_key = proxy
    messages = [{"role": m.role.value, "content": m.content} for m in request.messages]

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json={"model": request.model, "messages": messages, "stream": True},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    logger.warning("CLIProxy error %d: %s", resp.status_code, body[:200])
                    yield ChatStreamEvent(kind="error", payload=f"Proxy error {resp.status_code}")
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    if text := delta.get("content"):
                        yield ChatStreamEvent(kind="token", payload=text)
                    if choice.get("finish_reason"):
                        usage = data.get("usage", {})
                        yield ChatStreamEvent(kind="done", payload={
                            "finish_reason": choice["finish_reason"],
                            "tokens_in": usage.get("prompt_tokens"),
                            "tokens_out": usage.get("completion_tokens"),
                            "model": request.model,
                        })
    except httpx.ConnectError:
        logger.warning("Could not connect to CLIProxyAPI at %s", base_url)
        yield ChatStreamEvent(kind="error", payload=f"Could not connect to CLIProxyAPI at {base_url}")
    except httpx.TimeoutException:
        logger.warning("CLIProxyAPI request timed out")
        yield ChatStreamEvent(kind="error", payload="CLIProxyAPI request timed out")
    except Exception as exc:
        logger.warning("CLIProxyAPI chat error: %s", exc, exc_info=True)
        yield ChatStreamEvent(kind="error", payload=f"CLIProxyAPI error: {exc}")
