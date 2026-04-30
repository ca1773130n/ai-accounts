"""Negative tests for forward_cliproxy_callback's SSRF guard.

The forwarder takes an attacker-controlled URL and issues an HTTP GET to it.
The allowlist guards against SSRF: scheme, host, port, path. These tests
make sure the guard rejects every traversal / scheme / host / port / path
exploit pattern we've considered.
"""

import pytest

from ai_accounts_core.cliproxy.manager import forward_cliproxy_callback


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url, reason_substring",
    [
        # Wrong scheme.
        ("file:///etc/passwd", "http or https"),
        ("ftp://localhost:1455/auth/callback?code=x&state=y", "http or https"),
        ("javascript:alert(1)", "http or https"),
        # Wrong host (would let the forwarder reach external hosts).
        ("http://evil.com:1455/auth/callback?code=x&state=y", "must target localhost"),
        ("http://169.254.169.254/auth/callback?code=x&state=y", "must target localhost"),
        ("http://0.0.0.0:1455/auth/callback?code=x&state=y", "must target localhost"),
        # Wrong port.
        ("http://localhost:22/auth/callback?code=x&state=y", "port 22 not allowed"),
        ("http://localhost:80/auth/callback?code=x&state=y", "port 80 not allowed"),
        ("http://localhost:6379/auth/callback?code=x&state=y", "port 6379 not allowed"),
        # Path traversal — segment ".." inside an allowed prefix.
        ("http://localhost:1455/auth/../etc/passwd?code=x", "traversal"),
        ("http://localhost:1455/callback/..?code=x", "traversal"),
        # URL-encoded traversal (urlparse leaves %2E.%2E in path).
        ("http://localhost:1455/auth/callback/%2e%2e/etc?code=x", "traversal"),
        # Path not in allowlist.
        ("http://localhost:1455/admin?code=x&state=y", "path not allowed"),
        ("http://localhost:1455/?code=x&state=y", "path not allowed"),
    ],
)
async def test_ssrf_guard_rejects(url, reason_substring):
    result = await forward_cliproxy_callback(url)
    assert result["status"] == "error", f"expected reject for {url!r}, got {result!r}"
    assert reason_substring in result["message"], (
        f"expected '{reason_substring}' in error for {url!r}, got {result['message']!r}"
    )


@pytest.mark.asyncio
async def test_ssrf_guard_accepts_canonical_callback():
    """Sanity: the well-known cliproxy callback path passes the guard
    (would only fail at the upstream HTTP step, not the guard)."""
    # We use port 65535 (allowed? no — it'll fail with "port not allowed").
    # The point is to confirm the guard logic accepts /auth/callback path.
    # Use a never-bound port: actual upstream will fail but with a
    # connection error, not a guard reject.
    result = await forward_cliproxy_callback(
        "http://localhost:1455/auth/callback?code=fake&state=fake"
    )
    # Result is either:
    #   - "completed" (if a server is listening on 1455)
    #   - upstream error from connection-refused, but NOT a guard reject.
    if result["status"] == "error":
        assert "not allowed" not in result["message"], (
            f"guard wrongly rejected canonical URL: {result['message']!r}"
        )
        assert "traversal" not in result["message"]
