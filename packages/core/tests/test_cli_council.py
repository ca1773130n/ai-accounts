from __future__ import annotations

import json

import httpx
import pytest
from ai_accounts_core.cli_council import _parse_sse, _progress, main


def _sse_frames(*payloads: dict) -> bytes:
    return b"".join(f"event: council\ndata: {json.dumps(p)}\n\n".encode() for p in payloads)


def _mock_client(monkeypatch, handler) -> None:
    """Route the CLI's httpx.Client through a MockTransport."""
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )


def test_parse_sse_extracts_data_payloads():
    lines = [
        "event: council",
        'data: {"kind": "council_start", "payload": {"members": []}}',
        "",
        ": heartbeat 123",
        "data: not-json",  # tolerated, skipped
        'data: {"kind": "decision", "payload": {"choice": 1}}',
    ]
    events = list(_parse_sse(lines))
    assert [e["kind"] for e in events] == ["council_start", "decision"]


def test_progress_lines():
    assert "council convened" in _progress(
        {
            "kind": "council_start",
            "payload": {"members": [{"role": "architect", "account_label": "A1"}]},
        }
    )
    assert _progress({"kind": "position", "role": "architect", "option": 2}).startswith("position")
    assert _progress({"kind": "decision", "payload": {}}) is None  # decision goes to stdout


def test_main_requires_two_options(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["-q", "which?", "-o", "only one"])
    assert exc.value.code == 2


def test_main_wire_contract_decision(monkeypatch, capsys):
    """Locks the HTTP contract the Claude Code skill depends on: request path,
    auth header, body shape, decision JSON on stdout, exit 0."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse_frames(
                {"kind": "council_start", "payload": {"members": []}},
                {"kind": "position", "role": "architect", "option": 1},
                {"kind": "decision", "payload": {"choice": 1, "choice_label": "A"}},
            ),
            headers={"content-type": "text/event-stream"},
        )

    _mock_client(monkeypatch, handler)
    rc = main(["-q", "which?", "-o", "A", "-o", "B", "--api-key", "sk-k", "--json"])
    out = capsys.readouterr()

    assert rc == 0
    assert seen["path"] == "/api/v1/council/"
    assert seen["auth"] == "Bearer sk-k"
    assert seen["body"] == {"question": "which?", "options": ["A", "B"], "context": "", "rounds": 1}
    assert json.loads(out.out) == {"choice": 1, "choice_label": "A"}
    assert out.err == ""  # --json keeps stderr silent


def test_main_council_error_exits_nonzero(monkeypatch, capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse_frames({"kind": "council_error", "error": "no READY accounts"}),
            headers={"content-type": "text/event-stream"},
        )

    _mock_client(monkeypatch, handler)
    rc = main(["-q", "q", "-o", "A", "-o", "B", "--json"])
    out = capsys.readouterr()
    assert rc == 1
    assert out.out == ""
    assert "no READY accounts" in out.err


def test_main_non_200_exits_nonzero(monkeypatch, capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"code": "credential_unreadable"}})

    _mock_client(monkeypatch, handler)
    rc = main(["-q", "q", "-o", "A", "-o", "B"])
    assert rc == 1
    assert "503" in capsys.readouterr().err
