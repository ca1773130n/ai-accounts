from pathlib import Path

from ai_accounts_core.login import LoginSession
from ai_accounts_core.metadata import BackendMetadata
from ai_accounts_core.protocols.backend import BackendProtocol
from ai_accounts_core.testing import FakeBackend


def test_fake_backend_has_metadata():
    assert isinstance(FakeBackend.metadata, BackendMetadata)
    assert FakeBackend.metadata.kind == "fake"


def test_fake_backend_begin_login_returns_session(tmp_path: Path):
    backend = FakeBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )
    assert isinstance(session, LoginSession)
    assert session.backend_kind == "fake"
    assert session.flow_kind == "api_key"


def test_backend_protocol_runtime_checkable():
    assert isinstance(FakeBackend(), BackendProtocol)
