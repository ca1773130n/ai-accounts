from ai_accounts_core.cliproxy import (
    forward_cliproxy_callback,
    is_cliproxy_installed,
)


def test_is_installed_returns_bool():
    assert isinstance(is_cliproxy_installed(), bool)


async def test_forward_callback_rejects_missing_code():
    result = await forward_cliproxy_callback("https://example.test/cb?state=abc")
    assert result["status"] == "error"
    assert "code" in result["message"].lower()


async def test_forward_callback_unreachable_port():
    # Port 1 is reserved; nothing listens there.
    result = await forward_cliproxy_callback("http://localhost:1/cb?code=x&state=y")
    assert result["status"] == "error"
