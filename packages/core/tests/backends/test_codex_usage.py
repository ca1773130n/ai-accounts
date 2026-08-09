from __future__ import annotations

import logging

import pytest
from ai_accounts_core.backends._base import warn_empty_usage_parse
from ai_accounts_core.backends.codex import CodexBackend

# Captured verbatim from a real HTTP 200 on 2026-07-27 (identifiers scrubbed).
# The previous fixture invented a top-level "rate_limits" list that this
# endpoint has never returned, so the parser stayed green while every real
# call produced zero windows. Keep this payload shaped like the wire.
REAL_USAGE_200 = {
    "user_id": "user-REDACTED",
    "account_id": "user-REDACTED",
    "email": "redacted@example.com",
    "plan_type": "pro",
    "rate_limit": {
        "allowed": True,
        "limit_reached": False,
        "primary_window": {
            "used_percent": 31,
            "limit_window_seconds": 604800,
            "reset_after_seconds": 480599,
            "reset_at": 1785611965,
        },
        "secondary_window": None,
    },
    "code_review_rate_limit": None,
    "additional_rate_limits": [
        {
            "limit_name": "GPT-5.3-Codex-Spark",
            "metered_feature": "codex_bengalfox",
            "rate_limit": {
                "allowed": True,
                "limit_reached": False,
                "primary_window": {
                    "used_percent": 0,
                    "limit_window_seconds": 604800,
                    "reset_after_seconds": 604800,
                    "reset_at": 1785736166,
                },
                "secondary_window": None,
            },
        }
    ],
    "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
    "spend_control": {"reached": False, "individual_limit": None},
    "rate_limit_reached_type": None,
    "promo": None,
}


@pytest.mark.asyncio
async def test_codex_usage_parses_the_real_wire_shape(tmp_path, httpx_mock):
    httpx_mock.add_response(url="https://chatgpt.com/backend-api/wham/usage", json=REAL_USAGE_200)
    windows = await CodexBackend().get_usage(b"some-token", isolation_dir=tmp_path)

    assert len(windows) == 2, "plan-wide primary window + the one additional limit"

    plan = windows[0]
    assert plan.window_type == "primary_window"
    assert plan.usage_percent == 31.0
    assert plan.resets_at is not None
    assert plan.resets_at.year == 2026

    spark = windows[1]
    assert spark.window_type == "GPT-5.3-Codex-Spark:primary_window"
    assert spark.usage_percent == 0.0
    assert spark.resets_at is not None


@pytest.mark.asyncio
async def test_codex_usage_never_reports_token_counts(tmp_path, httpx_mock):
    """The endpoint carries no token counts; nothing may invent them."""
    httpx_mock.add_response(url="https://chatgpt.com/backend-api/wham/usage", json=REAL_USAGE_200)
    windows = await CodexBackend().get_usage(b"some-token", isolation_dir=tmp_path)
    assert windows
    assert all(w.tokens_used is None and w.tokens_limit is None for w in windows)


@pytest.mark.asyncio
async def test_codex_usage_skips_a_window_with_no_percent(tmp_path, httpx_mock):
    """A missing used_percent means "not reported", which must not become 0."""
    httpx_mock.add_response(
        url="https://chatgpt.com/backend-api/wham/usage",
        json={"rate_limit": {"primary_window": {"reset_at": 1785611965}}},
    )
    windows = await CodexBackend().get_usage(b"some-token", isolation_dir=tmp_path)
    assert windows == []


@pytest.mark.asyncio
async def test_codex_usage_secondary_window_is_read_when_present(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://chatgpt.com/backend-api/wham/usage",
        json={
            "rate_limit": {
                "primary_window": {"used_percent": 60.0, "reset_at": 1744495200},
                "secondary_window": {"used_percent": 10.0},
            }
        },
    )
    windows = await CodexBackend().get_usage(b"some-token", isolation_dir=tmp_path)
    assert [(w.window_type, w.usage_percent) for w in windows] == [
        ("primary_window", 60.0),
        ("secondary_window", 10.0),
    ]
    assert windows[1].resets_at is None


@pytest.mark.asyncio
async def test_codex_usage_empty_credential_makes_no_request(tmp_path):
    """No httpx_mock here: an outbound call would fail the test."""
    assert await CodexBackend().get_usage(b"", isolation_dir=tmp_path) == []


@pytest.mark.asyncio
async def test_codex_usage_unparseable_body_returns_empty(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://chatgpt.com/backend-api/wham/usage", json=["not", "a", "dict"]
    )
    assert await CodexBackend().get_usage(b"tok", isolation_dir=tmp_path) == []


@pytest.mark.asyncio
async def test_codex_usage_api_error_returns_empty(tmp_path, httpx_mock):
    httpx_mock.add_response(url="https://chatgpt.com/backend-api/wham/usage", status_code=500)
    assert await CodexBackend().get_usage(b"some-token", isolation_dir=tmp_path) == []


# --------------------------------------------------------------------------
# The alarm that was missing
# --------------------------------------------------------------------------
#
# The original parser read a top-level `rate_limits` list this endpoint has
# never returned, so every call produced [] — indistinguishable from a quiet
# account. Its fixture mocked those invented keys, so the suite stayed green
# while live usage silently read as empty. These pin the warning that makes
# the next shape drift visible instead of silent.

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


@pytest.mark.asyncio
async def test_warns_when_200_parses_to_no_windows(tmp_path, httpx_mock, caplog):
    """A 200 yielding nothing must say so, and name the keys it actually got."""
    # Exactly the old bug: well-formed, but none of the keys this parser reads.
    httpx_mock.add_response(url=USAGE_URL, json={"rate_limits": [{"used_percent": 42}]})

    with caplog.at_level(logging.WARNING):
        windows = await CodexBackend().get_usage(b"tok", isolation_dir=tmp_path)

    assert windows == []
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "no usage windows parsed" in joined
    assert "rate_limits" in joined, "the warning must name the keys actually returned"


@pytest.mark.asyncio
async def test_no_warning_when_windows_parse(tmp_path, httpx_mock, caplog):
    """A healthy response stays quiet — an alarm that always fires is noise."""
    httpx_mock.add_response(url=USAGE_URL, json=REAL_USAGE_200)

    with caplog.at_level(logging.WARNING):
        windows = await CodexBackend().get_usage(b"tok", isolation_dir=tmp_path)

    assert len(windows) == 2
    assert not [r for r in caplog.records if "no usage windows parsed" in r.getMessage()]


def test_warning_names_keys_but_never_leaks_values(caplog):
    """Only key NAMES are logged — values carry quota figures and account ids."""
    with caplog.at_level(logging.WARNING):
        warn_empty_usage_parse(
            logging.getLogger("t"), "codex", {"account_id": "acct_SECRET", "plan_type": "pro"}
        )

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "account_id" in joined and "plan_type" in joined
    assert "acct_SECRET" not in joined
