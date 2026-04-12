"""Shared CLIProxyAPI chat routing for CLI-browser-authenticated accounts."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent


async def _chat_via_cliproxy(request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
    """Route chat through CLIProxyAPI's OpenAI-compatible endpoint.

    Used when credential is empty (CLI-browser/OAuth login) — the CLI
    manages its own credentials and CLIProxyAPI exposes them via
    an OpenAI-compatible API.
    """
    from ai_accounts_core.cliproxy import detect_cliproxy

    proxy = detect_cliproxy()
    if proxy is None:
        yield ChatStreamEvent(
            kind="error",
            payload="CLIProxyAPI not running — install and start cliproxyapi, or use an API key",
        )
        return
    base_url, api_key = proxy
    messages = [{"role": m.role.value, "content": m.content} for m in request.messages]
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
                yield ChatStreamEvent(kind="error", payload=f"Proxy error {resp.status_code}")
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                data = json.loads(payload)
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
