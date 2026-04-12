from unittest.mock import MagicMock

from litestar import Request

from ai_accounts_litestar.errors import service_error_handler


def test_non_service_error_returns_generic_message():
    """Fallback handler must not leak internal details via str(exc)."""
    mock_request = MagicMock(spec=Request)
    exc = RuntimeError("secret/path/to/credentials.json failed")
    response = service_error_handler(mock_request, exc)
    body = response.content
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An internal error occurred"
    assert "secret" not in body["error"]["message"]
    assert "credentials" not in body["error"]["message"]
