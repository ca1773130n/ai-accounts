from __future__ import annotations

import logging

import pytest
from ai_accounts_core.backends.claude import ClaudeBackend

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# Captured from a real HTTP 200 on 2026-08-09 (strings scrubbed, numbers kept).
#
# The previous fixture invented a top-level "windows" list. There is no such
# key, so the parser produced zero windows on every real call while this test
# stayed green — the identical failure the codex parser had. Each rolling
# window is its OWN top-level key, or null when it does not apply to the plan.
REAL_USAGE_200 = {
    "five_hour": {
        "utilization": 2.0,
        "resets_at": "2026-08-09T10:49:59.636207+00:00",
        "limit_dollars": None,
        "used_dollars": None,
        "remaining_dollars": None,
    },
    "seven_day": {
        "utilization": 64.0,
        "resets_at": "2026-08-12T17:59:59.636231+00:00",
        "limit_dollars": None,
        "used_dollars": None,
        "remaining_dollars": None,
    },
    # Null for a plan tier the account does not have. Must be SKIPPED, not
    # read as 0% — an unused tier reported as 0 looks like a fresh quota.
    "seven_day_opus": None,
    "seven_day_sonnet": None,
    "seven_day_cowork": None,
    # Internal codenames, all present on the verified response. They are why
    # the parser discovers windows instead of enumerating a hardcoded list.
    "nimbus_quill": {
        "utilization": 0.0,
        "resets_at": None,
        "limit_dollars": None,
        "used_dollars": None,
        "remaining_dollars": None,
    },
    "tangelo": None,
    "cinder_cove": None,
    "amber_ladder": None,
    "iguana_necktie": None,
    "omelette_promotional": None,
    "extra_usage": {
        "is_enabled": False,
        "monthly_limit": None,
        "utilization": None,  # not a number -> not a window
        "user_disabled": True,
    },
    # Repeats the same percentages; reading it too would double-report.
    "limits": [
        {"kind": "five_hour", "group": "default", "percent": 2, "is_active": False},
    ],
    "spend": {"percent": 0, "enabled": False},
    "member_dashboard_available": False,
}


@pytest.mark.asyncio
async def test_parses_the_real_wire_shape(tmp_path, httpx_mock):
    httpx_mock.add_response(url=USAGE_URL, json=REAL_USAGE_200)
    windows = await ClaudeBackend().get_usage(b"sk-ant-oat01-xxx", isolation_dir=tmp_path)

    by_name = {w.window_type: w for w in windows}
    assert set(by_name) == {"five_hour", "seven_day", "nimbus_quill"}, (
        "only top-level objects carrying a NUMERIC utilization are windows"
    )
    assert by_name["five_hour"].usage_percent == 2.0
    assert by_name["seven_day"].usage_percent == 64.0
    assert by_name["seven_day"].resets_at is not None
    # resets_at may legitimately be null even on a live window.
    assert by_name["nimbus_quill"].resets_at is None
    # No token figures exist on this endpoint; never fabricate them.
    assert all(w.tokens_used is None and w.tokens_limit is None for w in windows)


@pytest.mark.asyncio
async def test_null_window_is_skipped_not_read_as_zero(tmp_path, httpx_mock):
    """A plan tier the account lacks must be absent, not reported at 0%."""
    httpx_mock.add_response(url=USAGE_URL, json=REAL_USAGE_200)
    windows = await ClaudeBackend().get_usage(b"sk-ant-oat01-xxx", isolation_dir=tmp_path)
    assert "seven_day_opus" not in {w.window_type for w in windows}


@pytest.mark.asyncio
async def test_oauth_access_token_is_not_mistaken_for_an_api_key(tmp_path, httpx_mock):
    """`sk-ant-oat…` is an OAuth token and DOES reach this endpoint.

    The guard used to match the bare `sk-ant-` prefix, which console API keys
    and OAuth access tokens share, so every real credential was rejected
    before a request went out. That is one of two independent reasons this
    method always returned [] — and it hid the other, since fixing either
    alone still yields an empty list.
    """
    httpx_mock.add_response(url=USAGE_URL, json=REAL_USAGE_200)
    windows = await ClaudeBackend().get_usage(b"sk-ant-oat01-xxx", isolation_dir=tmp_path)
    assert windows, "an OAuth access token must not be short-circuited"


@pytest.mark.asyncio
async def test_console_api_key_still_short_circuits(tmp_path):
    """`sk-ant-api…` genuinely cannot use the OAuth endpoint — no request."""
    windows = await ClaudeBackend().get_usage(b"sk-ant-api03-xxx", isolation_dir=tmp_path)
    assert windows == []


@pytest.mark.asyncio
async def test_warns_when_200_parses_to_no_windows(tmp_path, httpx_mock, caplog):
    """The alarm that was missing: a 200 yielding nothing must say so."""
    httpx_mock.add_response(url=USAGE_URL, json={"windows": [{"utilization": 5}]})

    with caplog.at_level(logging.WARNING):
        windows = await ClaudeBackend().get_usage(b"sk-ant-oat01-x", isolation_dir=tmp_path)

    assert windows == []
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "no usage windows parsed" in joined
    assert "windows" in joined, "the warning must name the keys actually returned"


@pytest.mark.asyncio
async def test_api_error_returns_empty(tmp_path, httpx_mock):
    httpx_mock.add_response(url=USAGE_URL, status_code=403)
    windows = await ClaudeBackend().get_usage(b"sk-ant-oat01-x", isolation_dir=tmp_path)
    assert windows == []
