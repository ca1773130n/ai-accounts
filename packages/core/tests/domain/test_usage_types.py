from datetime import UTC, datetime

import msgspec
from ai_accounts_core.domain.usage import (
    AccountHealth,
    FallbackChainEntry,
    PickResult,
    UsageWindow,
)


def test_usage_window_roundtrip():
    w = UsageWindow(
        window_type="daily",
        usage_percent=42.5,
        resets_at=datetime(2026, 4, 13, 0, 0, tzinfo=UTC),
        tokens_used=1000,
        tokens_limit=5000,
    )
    data = msgspec.json.encode(w)
    decoded = msgspec.json.decode(data, type=UsageWindow)
    assert decoded == w
    assert decoded.window_type == "daily"
    assert decoded.tokens_used == 1000


def test_usage_window_optional_fields():
    w = UsageWindow(
        window_type="monthly",
        usage_percent=0.0,
        resets_at=None,
    )
    data = msgspec.json.encode(w)
    decoded = msgspec.json.decode(data, type=UsageWindow)
    assert decoded == w
    assert decoded.tokens_used is None
    assert decoded.tokens_limit is None


def test_account_health_roundtrip():
    window = UsageWindow(
        window_type="daily",
        usage_percent=75.0,
        resets_at=datetime(2026, 4, 13, 0, 0, tzinfo=UTC),
    )
    health = AccountHealth(
        backend_id="bkd-abc123",
        kind="claude",
        windows=(window,),
        rate_limited_until=datetime(2026, 4, 12, 14, 0, tzinfo=UTC),
        rate_limit_reason="quota exceeded",
        last_used_at=datetime(2026, 4, 12, 12, 0, tzinfo=UTC),
        last_polled_at=datetime(2026, 4, 12, 12, 30, tzinfo=UTC),
    )
    data = msgspec.json.encode(health)
    decoded = msgspec.json.decode(data, type=AccountHealth)
    assert decoded == health
    assert decoded.windows[0].window_type == "daily"


def test_account_health_defaults():
    health = AccountHealth(
        backend_id="bkd-abc123",
        kind="claude",
        windows=(),
    )
    assert health.rate_limited_until is None
    assert health.rate_limit_reason is None
    assert health.last_used_at is None
    assert health.last_polled_at is None


def test_fallback_chain_entry_roundtrip():
    entry = FallbackChainEntry(backend_id="bkd-abc123", priority=1)
    data = msgspec.json.encode(entry)
    decoded = msgspec.json.decode(data, type=FallbackChainEntry)
    assert decoded == entry
    assert decoded.priority == 1


def test_pick_result_roundtrip():
    result = PickResult(
        backend_id="bkd-abc123",
        kind="claude",
        credential=b"\x01\x02\x03",
        isolation_dir="/tmp/iso/bkd-abc123",
        retry_after=datetime(2026, 4, 12, 14, 0, tzinfo=UTC),
    )
    data = msgspec.json.encode(result)
    decoded = msgspec.json.decode(data, type=PickResult)
    assert decoded == result
    assert decoded.credential == b"\x01\x02\x03"


def test_pick_result_defaults():
    result = PickResult(
        backend_id="bkd-abc123",
        kind="claude",
        credential=b"key",
        isolation_dir="/tmp/iso",
    )
    assert result.retry_after is None
