from ai_accounts_core.cliproxy import (
    forward_cliproxy_callback,
    is_cliproxy_installed,
)


def test_is_installed_returns_bool():
    assert isinstance(is_cliproxy_installed(), bool)


async def test_forward_callback_rejects_missing_code():
    result = await forward_cliproxy_callback("http://localhost:54545/cb?state=abc")
    assert result["status"] == "error"
    assert "code" in result["message"].lower()


async def test_forward_callback_unreachable_port():
    # Port 1 is not in the allowlist; rejected by SSRF guard.
    result = await forward_cliproxy_callback("http://localhost:1/cb?code=x&state=y")
    assert result["status"] == "error"
    assert "port" in result["message"].lower()


async def test_forward_callback_rejects_disallowed_port():
    result = await forward_cliproxy_callback("http://localhost:9999/callback?code=x&state=y")
    assert result["status"] == "error"
    assert "port" in result["message"].lower()


async def test_forward_callback_rejects_path_traversal():
    result = await forward_cliproxy_callback("http://localhost:54545/admin/delete?code=x&state=y")
    assert result["status"] == "error"
    assert "path" in result["message"].lower()


async def test_forward_callback_rejects_external_host():
    result = await forward_cliproxy_callback("http://evil.com:54545/callback?code=x&state=y")
    assert result["status"] == "error"
    assert "localhost" in result["message"].lower()


async def test_forward_callback_allows_valid_url():
    # Port 54545 with /callback path — passes validation but httpx fails (nothing listening)
    result = await forward_cliproxy_callback("http://localhost:54545/callback?code=x&state=y")
    # Should reach the httpx call and fail with connection error, not validation error
    assert result["status"] == "error"
    assert "reach" in result["message"].lower() or "connect" in result["message"].lower()
