"""Shared CLIProxyAPI chat routing for CLI-browser-authenticated accounts."""

from __future__ import annotations

import gzip
import json
import logging
import zlib
from collections.abc import AsyncIterator

import httpx

from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent

logger = logging.getLogger(__name__)


def _maybe_decompress(body: bytes, encoding: str) -> bytes:
    """Decompress an httpx streaming-response error body when the upstream
    sent a Content-Encoding header. httpx's streaming mode does not auto-
    decode, so error bodies can land here as raw gzip/deflate bytes — which
    used to be stringified and rendered as garbage in the UI.

    Falls back to the original body on any decompression failure (e.g.
    declared encoding but body is plaintext, truncated stream)."""
    enc = (encoding or "").lower().strip()
    if enc == "gzip":
        try:
            return gzip.decompress(body)
        except (OSError, EOFError, zlib.error):
            pass
    elif enc in {"deflate", "compress", "x-deflate"}:
        try:
            return zlib.decompress(body)
        except zlib.error:
            try:
                return zlib.decompress(body, -zlib.MAX_WBITS)
            except zlib.error:
                pass
    # Heuristic fallback: detect gzip magic bytes (1f 8b) even when the
    # server forgot the Content-Encoding header.
    if body[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(body)
        except (OSError, EOFError, zlib.error):
            pass
    return body


def _accumulate_tool_calls(pending: dict[int, dict[str, str]], fragments: object) -> None:
    """Merge one delta's `tool_calls` fragments into `pending`, keyed by the
    upstream `index`. OpenAI sends `id` and `function.name` on the first
    fragment of a call and streams `function.arguments` across the rest, so a
    single fragment is never a whole call."""
    if not isinstance(fragments, list):
        return
    for frag in fragments:
        if not isinstance(frag, dict):
            continue
        index = frag.get("index", 0)
        if not isinstance(index, int):
            continue
        call = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
        if call_id := frag.get("id"):
            call["id"] = str(call_id)
        function = frag.get("function")
        if not isinstance(function, dict):
            continue
        if name := function.get("name"):
            call["name"] = str(name)
        if args := function.get("arguments"):
            call["arguments"] += str(args)


def _drain_tool_calls(pending: dict[int, dict[str, str]]) -> list[ChatStreamEvent]:
    """Turn the accumulated fragments into one event per completed call, in
    upstream index order, and clear `pending`."""
    events = [
        ChatStreamEvent(kind="tool_call", payload=dict(call)) for _, call in sorted(pending.items())
    ]
    pending.clear()
    return events


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
    body_json: dict[str, object] = {
        "model": request.model,
        "messages": messages,
        "stream": True,
    }
    # Function calling rides on `params`, the same extension channel
    # `max_tokens` uses in the API-key adapters. Send the OpenAI shape
    # verbatim; omit the keys entirely when there are no tools, since some
    # servers read `tools: []` as "tools forbidden" rather than "unspecified".
    if tools := request.params.get("tools"):
        body_json["tools"] = tools
        # `tool_choice` is only meaningful alongside `tools`.
        if "tool_choice" in request.params:
            body_json["tool_choice"] = request.params["tool_choice"]

    try:
        async with (
            httpx.AsyncClient() as client,
            client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json=body_json,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            ) as resp,
        ):
            if resp.status_code != 200:
                body = await resp.aread()
                encoding = ""
                headers = getattr(resp, "headers", None)
                if headers is not None:
                    try:
                        encoding = headers.get("content-encoding", "") or ""
                    except (AttributeError, TypeError):
                        encoding = ""
                body = _maybe_decompress(body, encoding)
                logger.warning("CLIProxy error %d: %s", resp.status_code, body[:200])
                # Surface the upstream error to the UI. CLIProxyAPI mostly
                # returns OpenAI-style {"error":{"message":...,"code":...}};
                # parse that out, fall back to a sanitized body excerpt.
                detail: str | None = None
                try:
                    parsed = json.loads(body or b"{}")
                    if isinstance(parsed, dict):
                        err = parsed.get("error")
                        if isinstance(err, dict):
                            detail = err.get("message") or err.get("code")
                        elif isinstance(err, str):
                            detail = err
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
                if not detail:
                    # Last-resort: short text excerpt with control chars stripped.
                    text = body.decode("utf-8", errors="replace")[:200]
                    detail = " ".join(text.split())
                msg = (
                    f"Proxy error {resp.status_code}: {detail}"
                    if detail
                    else f"Proxy error {resp.status_code}"
                )
                yield ChatStreamEvent(kind="error", payload=msg)
                return
            # Tool-call fragments accumulate here until the call is complete.
            pending_tool_calls: dict[int, dict[str, str]] = {}
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
                if fragments := delta.get("tool_calls"):
                    _accumulate_tool_calls(pending_tool_calls, fragments)
                if choice.get("finish_reason"):
                    # Flush before `done` — the upstream sends every fragment
                    # ahead of finish_reason="tool_calls", and consumers may
                    # stop reading once they see the done event.
                    for event in _drain_tool_calls(pending_tool_calls):
                        yield event
                    usage = data.get("usage", {})
                    yield ChatStreamEvent(
                        kind="done",
                        payload={
                            "finish_reason": choice["finish_reason"],
                            "tokens_in": usage.get("prompt_tokens"),
                            "tokens_out": usage.get("completion_tokens"),
                            "model": request.model,
                        },
                    )
            # Proxies that end the stream without a finish_reason would
            # otherwise swallow the call entirely.
            for event in _drain_tool_calls(pending_tool_calls):
                yield event
    except httpx.ConnectError:
        logger.warning("Could not connect to CLIProxyAPI at %s", base_url)
        yield ChatStreamEvent(
            kind="error", payload=f"Could not connect to CLIProxyAPI at {base_url}"
        )
    except httpx.TimeoutException:
        logger.warning("CLIProxyAPI request timed out")
        yield ChatStreamEvent(kind="error", payload="CLIProxyAPI request timed out")
    except Exception as exc:
        logger.warning("CLIProxyAPI chat error: %s", exc, exc_info=True)
        yield ChatStreamEvent(kind="error", payload=f"CLIProxyAPI error: {exc}")
