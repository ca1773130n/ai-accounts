"""Smoke tests that protocol modules import and expose expected symbols."""

from ai_accounts_core.protocols import storage, vault, auth, backend


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
    assert hasattr(backend, "LoginFlow")
    assert hasattr(backend, "ChatRequest")
    assert hasattr(backend, "PtyRequest")


def test_transport_protocol_exports():
    from ai_accounts_core.protocols import transport
    assert hasattr(transport, "TransportProtocol")
