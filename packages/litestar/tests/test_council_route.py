"""POST /api/v1/council — SSE wire-shape lock for the council route."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.protocols.backend import ChatStreamEvent
from ai_accounts_core.testing import FakeBackend, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig
from litestar.testing import AsyncTestClient


class _VotingFake(FakeBackend):
    async def chat(self, request, credential, *, isolation_dir):
        yield ChatStreamEvent(kind="token", payload="lens argument.\nVOTE: 2")
        yield ChatStreamEvent(kind="done", payload={})


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app(
        AiAccountsConfig(
            env="development",
            storage=SqliteStorage(str(tmp_path / "t.db")),
            vault=FakeVault(),
            auth=NoAuth(),
            backends=(_VotingFake(),),
            backend_dirs_path=tmp_path / "iso",
        )
    )
    async with AsyncTestClient(app=app) as c:
        yield c


def _parse_sse_events(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        for line in block.strip().split("\n"):
            if line.startswith("data:"):
                events.append(json.loads(line.removeprefix("data:").strip()))
    return events


async def _add_ready_account(client) -> str:
    r = await client.post("/api/v1/backends/", json={"kind": "fake", "display_name": "T"})
    assert r.status_code == 201
    backend_id = r.json()["id"]
    provide = client.app.dependencies["account_service"]
    svc = provide.dependency()
    await svc.store_credential(backend_id, b"sk-fake-test")
    await svc.validate(backend_id)
    return backend_id


@pytest.mark.asyncio
async def test_council_streams_deliberation_to_decision(client):
    await _add_ready_account(client)
    r = await client.post(
        "/api/v1/council/",
        json={
            "question": "Which path?",
            "options": ["Path A", "Path B"],
            "context": "small test",
            "rounds": 1,
        },
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    assert "event: council" in r.text

    events = _parse_sse_events(r.text)
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "council_start"
    assert kinds.count("position") == 5
    assert kinds.count("rebuttal") == 5
    assert "votes" in kinds
    assert kinds[-1] == "decision"

    start = events[0]["payload"]
    assert start["question"] == "Which path?"
    assert len(start["members"]) == 5

    decision = events[-1]["payload"]
    assert decision["choice"] == 2
    assert decision["choice_label"] == "Path B"
    assert decision["tally"] == {"Path B": 5}
    assert decision["decided_by"] in ("chairman", "majority_fallback")


@pytest.mark.asyncio
async def test_council_without_accounts_errors_in_stream(client):
    r = await client.post(
        "/api/v1/council/",
        json={"question": "Which?", "options": ["A", "B"]},
    )
    assert r.status_code == 200
    events = _parse_sse_events(r.text)
    assert events[-1]["kind"] == "council_error"
    assert "no READY accounts" in events[-1]["error"]
