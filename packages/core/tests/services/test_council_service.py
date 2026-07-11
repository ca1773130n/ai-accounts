from __future__ import annotations

from pathlib import Path

import pytest
from ai_accounts_core.protocols.backend import ChatStreamEvent
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.council import (
    CouncilService,
    _parse_chair_json,
    _parse_vote,
)
from ai_accounts_core.services.scheduler import AccountScheduler
from ai_accounts_core.testing import FakeBackend, FakeStorage, FakeVault

_OPTIONS = ["Option Alpha", "Option Beta", "Option Gamma"]


class _VotingFake(FakeBackend):
    """Every call argues briefly and votes a fixed option; the credential is
    echoed so per-account attribution is visible in outputs."""

    def __init__(self, vote: int = 2) -> None:
        super().__init__()
        self._vote = vote

    async def chat(self, request, credential, *, isolation_dir):
        self.calls.append(("chat", request))
        yield ChatStreamEvent(
            kind="token",
            payload=f"[{credential.decode()}] arguing my lens.\nVOTE: {self._vote}",
        )
        yield ChatStreamEvent(kind="done", payload={})


class _ChairJsonFake(FakeBackend):
    """Answers everything with a chairman-style JSON (no VOTE line)."""

    async def chat(self, request, credential, *, isolation_dir):
        yield ChatStreamEvent(
            kind="token",
            payload='{"choice": 1, "confidence": 0.9, "rationale": "r", "dissent": "d"}',
        )
        yield ChatStreamEvent(kind="done", payload={})


class _FlakyFake(_VotingFake):
    """Raises for accounts whose credential ends in '-bad'."""

    async def chat(self, request, credential, *, isolation_dir):
        if credential.endswith(b"-bad"):
            raise RuntimeError("endpoint down")
            yield  # pragma: no cover — makes this an async generator
        async for ev in super().chat(request, credential, isolation_dir=isolation_dir):
            yield ev


async def _make_council(
    tmp_path: Path, fake: FakeBackend, credentials: list[bytes]
) -> CouncilService:
    storage = FakeStorage()
    vault = FakeVault()
    accounts = AccountService(
        storage=storage,
        vault=vault,
        backends={fake.kind: fake},
        isolation_base_dir=tmp_path / "iso",
    )
    for i, cred in enumerate(credentials):
        b = await accounts.create("fake", display_name=f"A{i + 1}")
        await accounts.store_credential(b.id, cred)
        await accounts.validate(b.id)
    scheduler = AccountScheduler(account_service=accounts, storage=storage)
    return CouncilService(account_service=accounts, scheduler=scheduler)


async def _run(council: CouncilService, **kw):
    defaults = {"question": "Which way?", "options": list(_OPTIONS), "rounds": 1}
    defaults.update(kw)
    return [e async for e in council.convene(**defaults)]


def _by_kind(events, kind):
    return [e for e in events if e.kind == kind]


def test_parse_vote():
    assert _parse_vote("blah\nVOTE: 2", 3) == 2
    assert _parse_vote("VOTE: 1 ... changed my mind\nVOTE: 3", 3) == 3  # last wins
    assert _parse_vote("vote: (2)", 3) == 2  # case/paren tolerant
    assert _parse_vote("VOTE: 9", 3) is None  # out of range
    assert _parse_vote("no vote here", 3) is None


def test_parse_chair_json():
    ok = _parse_chair_json('preamble {"choice": 2, "rationale": "x"} trailer', 3)
    assert ok is not None and ok["choice"] == 2
    assert _parse_chair_json('{"choice": 7}', 3) is None  # out of range
    assert _parse_chair_json("not json at all", 3) is None
    assert _parse_chair_json('{"choice": "2"}', 3) is None  # non-int choice


@pytest.mark.asyncio
async def test_single_account_backs_all_roles_majority_decision(tmp_path):
    """One account: five role-members debate on it; a non-JSON chairman falls
    back to the members' majority vote."""
    council = await _make_council(tmp_path, _VotingFake(vote=2), [b"sk-fake-1"])
    events = await _run(council)

    start = _by_kind(events, "council_start")[0]
    roster = start.payload["members"]
    assert [m["role"] for m in roster] == [
        "pragmatist",
        "architect",
        "risk-analyst",
        "user-advocate",
        "contrarian",
    ]
    assert {m["account_label"] for m in roster} == {"A1"}

    positions = _by_kind(events, "position")
    assert len(positions) == 5
    assert all(p.option == 2 for p in positions)
    assert len(_by_kind(events, "rebuttal")) == 5

    votes = _by_kind(events, "votes")[0]
    assert votes.payload["tally"] == {"Option Beta": 5}

    decision = _by_kind(events, "decision")[0].payload
    assert decision["choice"] == 2
    assert decision["choice_label"] == "Option Beta"
    assert decision["decided_by"] == "majority_fallback"


@pytest.mark.asyncio
async def test_roles_round_robin_across_accounts(tmp_path):
    """Five roles over three accounts distribute A1,A2,A3,A1,A2."""
    council = await _make_council(
        tmp_path, _VotingFake(vote=1), [b"sk-fake-1", b"sk-fake-2", b"sk-fake-3"]
    )
    events = await _run(council, rounds=0)
    roster = _by_kind(events, "council_start")[0].payload["members"]
    assert [m["account_label"] for m in roster] == ["A1", "A2", "A3", "A1", "A2"]
    decision = _by_kind(events, "decision")[0].payload
    assert decision["choice"] == 1


@pytest.mark.asyncio
async def test_chairman_json_decides_without_votes(tmp_path):
    """When members cast no parseable votes but the chairman answers strict
    JSON, the chairman's choice stands."""
    council = await _make_council(tmp_path, _ChairJsonFake(), [b"sk-fake-1"])
    events = await _run(council)
    decision = _by_kind(events, "decision")[0].payload
    assert decision["decided_by"] == "chairman"
    assert decision["choice"] == 1
    assert decision["confidence"] == 0.9


@pytest.mark.asyncio
async def test_member_failures_respect_quorum(tmp_path):
    """A broken account errors its members but the council proceeds while at
    least two positions exist."""
    council = await _make_council(tmp_path, _FlakyFake(vote=3), [b"sk-fake-good", b"sk-fake-bad"])
    events = await _run(council, rounds=0)
    # Roles 2 and 4 sat on the bad account (A2) and errored.
    assert len(_by_kind(events, "member_error")) == 2
    assert len(_by_kind(events, "position")) == 3
    decision = _by_kind(events, "decision")[0].payload
    assert decision["choice"] == 3


@pytest.mark.asyncio
async def test_no_accounts_is_council_error(tmp_path):
    council = await _make_council(tmp_path, _VotingFake(), [])
    events = await _run(council)
    assert [e.kind for e in events] == ["council_error"]
    assert "no READY accounts" in events[0].error


@pytest.mark.asyncio
async def test_needs_two_options(tmp_path):
    council = await _make_council(tmp_path, _VotingFake(), [b"sk-fake-1"])
    events = await _run(council, options=["only one"])
    assert [e.kind for e in events] == ["council_error"]
