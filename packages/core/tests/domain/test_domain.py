from datetime import UTC, datetime

from ai_accounts_core.domain.backend import Backend, BackendCredential, BackendKind, BackendStatus
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.domain.principal import Principal


def test_backend_construction():
    backend = Backend(
        id="bkd-abc123",
        kind=BackendKind.CLAUDE,
        display_name="Claude main",
        config={},
        status=BackendStatus.READY,
        created_at=datetime.now(UTC),
    )
    assert backend.id == "bkd-abc123"
    assert backend.kind == BackendKind.CLAUDE
    assert backend.status is BackendStatus.READY


def test_backend_credential_never_exposes_plaintext():
    cred = BackendCredential(
        id="crd-xyz789",
        backend_id="bkd-abc123",
        ciphertext=b"\x01\x02\x03",
        key_id="kms://local/v1",
        created_at=datetime.now(UTC),
    )
    assert cred.ciphertext == b"\x01\x02\x03"
    assert not hasattr(cred, "plaintext")


def test_chat_message_roles():
    msg = ChatMessage(
        id="msg-1",
        session_id="sess-1",
        role=ChatRole.USER,
        content="hello",
        created_at=datetime.now(UTC),
    )
    assert msg.role is ChatRole.USER


def test_principal_identifies_caller():
    p = Principal(id="user:local", display_name="Local Dev", scopes=frozenset({"read", "write"}))
    assert "read" in p.scopes
