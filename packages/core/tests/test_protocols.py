"""Smoke tests that protocol modules import and expose expected symbols."""

from ai_accounts_core.protocols import auth, backend, storage, vault


def test_storage_protocol_exports():
    assert hasattr(storage, "StorageProtocol")
    assert hasattr(storage, "BackendRepository")
    assert hasattr(storage, "SessionRepository")
    assert hasattr(storage, "HistoryRepository")
    assert hasattr(storage, "OnboardingRepository")


def test_vault_protocol_exports():
    assert hasattr(vault, "VaultProtocol")
    assert hasattr(vault, "VaultError")


def test_auth_protocol_exports():
    assert hasattr(auth, "AuthProtocol")
    assert hasattr(auth, "RequestContext")


def test_backend_protocol_exports():
    assert hasattr(backend, "BackendProtocol")
    assert hasattr(backend, "ChatRequest")
    assert hasattr(backend, "PtyRequest")
    assert hasattr(backend, "Model")


def test_fake_backend_supported_login_flows():
    from ai_accounts_core.testing import FakeBackend

    fb = FakeBackend()
    assert hasattr(fb, "supported_login_flows")
    assert "api_key" in fb.supported_login_flows
    assert "oauth_device" in fb.supported_login_flows


def test_transport_protocol_exports():
    from ai_accounts_core.protocols import transport

    assert hasattr(transport, "TransportProtocol")
