import base64

import pytest

from ai_accounts_core.adapters.auth_apikey import ApiKeyAuth
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.adapters.vault_envkey import EnvKeyVault
from ai_accounts_core.backends import ClaudeBackend
from ai_accounts_core.testing import FakeVault

from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


@pytest.fixture
def real_vault(monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_VAULT_KEY", base64.b64encode(b"\x01" * 32).decode())
    return EnvKeyVault.from_env(env="production")


def test_production_mode_rejects_no_auth(real_vault, tmp_path):
    config = AiAccountsConfig(
        env="production",
        storage=SqliteStorage(str(tmp_path / "a.db")),
        vault=real_vault,
        auth=NoAuth(),
        backends=(ClaudeBackend(),),
        cors_origins=("https://example.com",),
        backend_dirs_path=tmp_path / "backend_dirs",
    )
    with pytest.raises(RuntimeError, match="NoAuth"):
        create_app(config)


def test_production_mode_rejects_wildcard_cors(real_vault, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_API_KEY", "test-token")
    config = AiAccountsConfig(
        env="production",
        storage=SqliteStorage(str(tmp_path / "a.db")),
        vault=real_vault,
        auth=ApiKeyAuth.from_env(),
        backends=(ClaudeBackend(),),
        cors_origins=("*",),
        backend_dirs_path=tmp_path / "backend_dirs",
    )
    with pytest.raises(RuntimeError, match="wildcard"):
        create_app(config)


def test_production_mode_rejects_empty_cors(real_vault, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_API_KEY", "test-token")
    config = AiAccountsConfig(
        env="production",
        storage=SqliteStorage(str(tmp_path / "a.db")),
        vault=real_vault,
        auth=ApiKeyAuth.from_env(),
        backends=(ClaudeBackend(),),
        cors_origins=(),
        backend_dirs_path=tmp_path / "backend_dirs",
    )
    with pytest.raises(RuntimeError, match="cors_origins"):
        create_app(config)


def test_production_mode_rejects_fake_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_API_KEY", "test-token")
    config = AiAccountsConfig(
        env="production",
        storage=SqliteStorage(str(tmp_path / "a.db")),
        vault=FakeVault(),
        auth=ApiKeyAuth.from_env(),
        backends=(ClaudeBackend(),),
        cors_origins=("https://example.com",),
        backend_dirs_path=tmp_path / "backend_dirs",
    )
    with pytest.raises(RuntimeError, match="fake"):
        create_app(config)


def test_production_mode_rejects_none_auth(real_vault, tmp_path):
    config = AiAccountsConfig(
        env="production",
        storage=SqliteStorage(str(tmp_path / "a.db")),
        vault=real_vault,
        auth=None,
        backends=(ClaudeBackend(),),
        cors_origins=("https://example.com",),
        backend_dirs_path=tmp_path / "backend_dirs",
    )
    with pytest.raises(RuntimeError, match="auth is unset"):
        create_app(config)


def test_development_mode_allows_all(tmp_path):
    config = AiAccountsConfig(
        env="development",
        storage=SqliteStorage(str(tmp_path / "a.db")),
        vault=FakeVault(),
        auth=NoAuth(),
        backends=(ClaudeBackend(),),
        backend_dirs_path=tmp_path / "backend_dirs",
    )
    app = create_app(config)
    assert app is not None
