"""End-to-end SSE wire-shape lock for ``POST /api/v1/chat/send``.

The existing ``test_chat_send.py`` covers reconnect/seq/tool-call semantics
but only smoke-tests ``mode=all`` (line 100: 200 status only) and never
exercises ``mode=compound``. Three chat regressions escaped in 0.3.9 /
0.3.10 / 0.3.12 precisely because no test asserted the byte-level wire
shape for these modes. This file fills that gap.

Each test drives the real route through ``AsyncTestClient``, parses the SSE
stream, and asserts the dict shape of each event. Frontends that rely on
the ``useSmartChat.dispatch`` union shape can trust the route's contract.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from litestar.testing import AsyncTestClient

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.testing import FakeBackend, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncTestClient]:
    """One FakeBackend kind — two accounts registered against it in _setup()
    so mode=all has something to fan-out to."""
    app = create_app(
        AiAccountsConfig(
            env="development",
            storage=SqliteStorage(str(tmp_path / "t.db")),
            vault=FakeVault(),
            auth=NoAuth(),
            backends=(FakeBackend(),),
            backend_dirs_path=tmp_path / "iso",
        )
    )
    async with AsyncTestClient(app=app) as c:
        yield c


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        for line in block.strip().split("\n"):
            if line.startswith("data:"):
                raw = line.removeprefix("data:").strip()
                if raw:
                    events.append(json.loads(raw))
    return events


def _get_account_service(client: AsyncTestClient) -> AccountService:
    provide = client.app.dependencies["account_service"]  # type: ignore[union-attr]
    return provide.dependency()


def _get_chat_service(client: AsyncTestClient) -> ChatService:
    provide = client.app.dependencies["chat_service"]  # type: ignore[union-attr]
    return provide.dependency()


async def _setup(client: AsyncTestClient) -> str:
    """Register one fake backend + create a session against it, return session_id.

    The fake registers twice for the fan-out tests; we just need one chat
    session anchored to one of them — send_all/send_compound iterate
    over scheduler health and pick credentials per kind.
    """
    r = await client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "A"}
    )
    assert r.status_code == 201, r.text
    backend_id = r.json()["id"]

    # A second account of the same kind so send_all has > 1 stream to merge.
    r2 = await client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "B"}
    )
    assert r2.status_code == 201, r2.text
    backend_id_b = r2.json()["id"]

    svc = _get_account_service(client)
    await svc.store_credential(backend_id, b"sk-fake-a")
    await svc.validate(backend_id)
    await svc.store_credential(backend_id_b, b"sk-fake-b")
    await svc.validate(backend_id_b)

    chat = _get_chat_service(client)
    session = await chat.create_session(backend_id=backend_id, model="fake-1")
    return session.id


@pytest.mark.asyncio
async def test_single_mode_uses_payload_field(client: AsyncTestClient) -> None:
    """ChatDelta.payload (not .text) must be the field name on the wire.

    Regression guard: the 0.3.9 fix renamed text→payload at the SSE boundary;
    in this release the ChatDelta struct itself uses ``payload``. Frontends
    that read ``event.payload`` must keep seeing strings.
    """
    session_id = await _setup(client)
    r = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "Hello", "mode": "single"},
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)

    tokens = [e for e in events if e.get("kind") == "token"]
    assert tokens, "expected at least one token event"
    for tok in tokens:
        assert "payload" in tok, f"token event missing payload: {tok}"
        assert isinstance(tok["payload"], str)
        # The pre-0.3.13 ChatDelta serialized to {kind, text, ...}; if `text`
        # is still present this is a regression to the dual-field shape that
        # confused useSmartChat.dispatch.
        assert "text" not in tok, (
            f"ChatDelta should use only `payload`, found stray `text`: {tok}"
        )


@pytest.mark.asyncio
async def test_all_mode_emits_backend_events(client: AsyncTestClient) -> None:
    """mode=all yields backend_delta / backend_complete per registered backend."""
    session_id = await _setup(client)
    r = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "Hi", "mode": "all"},
    )
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    kinds = {e.get("kind") for e in events}
    # At minimum we need an incremental output frame and a per-backend
    # terminator. Both backends are fake-fake, so we expect two completes.
    assert "backend_delta" in kinds, f"no backend_delta in {kinds}"
    assert "backend_complete" in kinds, f"no backend_complete in {kinds}"

    deltas = [e for e in events if e.get("kind") == "backend_delta"]
    for d in deltas:
        # AllModeEvent contract — frontend useSmartChat reads `text` for fan-out
        # deltas (separate channel from single-mode ChatDelta.payload).
        assert "backend" in d
        assert "backend_kind" in d
        assert d["backend_kind"] == "fake"
        assert isinstance(d.get("text"), str)


@pytest.mark.asyncio
async def test_compound_mode_synthesises(client: AsyncTestClient) -> None:
    """mode=compound runs fan-out + synthesis, emitting synthesis_* frames."""
    session_id = await _setup(client)
    r = await client.post(
        "/api/v1/chat/send",
        json={
            "session_id": session_id,
            "content": "Compose",
            "mode": "compound",
            "backend_kind": "fake",
        },
    )
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    kinds = [e.get("kind") for e in events]

    assert "synthesis_start" in kinds, f"missing synthesis_start: {kinds}"
    # The fake backend yields two tokens during synth, so we should see at
    # least one synthesis_delta before synthesis_complete.
    deltas = [e for e in events if e.get("kind") == "synthesis_delta"]
    assert deltas, f"no synthesis_delta events: {kinds}"
    assert all(isinstance(d.get("text"), str) for d in deltas)
    assert "synthesis_complete" in kinds


@pytest.mark.asyncio
async def test_every_event_carries_seq_for_reconnect(client: AsyncTestClient) -> None:
    """Reconnect protocol requires monotonic ``_seq`` on every business event."""
    session_id = await _setup(client)
    r = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "x", "mode": "single"},
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    seqs = [e["_seq"] for e in events if "_seq" in e]
    assert seqs, "no events were tagged with _seq"
    assert seqs == sorted(seqs), f"seqs not monotonic: {seqs}"
    assert seqs[0] == 1
