from datetime import UTC, datetime

import msgspec

from ai_accounts_core.protocols.backend import (
    CredentialLogin,
    LoginError,
    LoginResult,
    OAuthDeviceLogin,
)


def test_credential_login_roundtrip():
    login = CredentialLogin(credential=b"sk-ant-abc")
    encoded = msgspec.json.encode(login)
    decoded = msgspec.json.decode(encoded, type=LoginResult)
    assert decoded == login
    assert isinstance(decoded, CredentialLogin)


def test_oauth_device_login_roundtrip():
    login = OAuthDeviceLogin(
        verification_uri="https://accounts.google.com/o/oauth2/device/usercode",
        user_code="ABCD-1234",
        expires_at=datetime(2026, 4, 11, 18, 0, 0, tzinfo=UTC),
        handle="oauth-abc123",
    )
    encoded = msgspec.json.encode(login)
    decoded = msgspec.json.decode(encoded, type=LoginResult)
    assert decoded == login
    assert isinstance(decoded, OAuthDeviceLogin)


def test_login_error_roundtrip():
    err = LoginError(code="timeout", message="user did not complete auth in 15 minutes")
    encoded = msgspec.json.encode(err)
    decoded = msgspec.json.decode(encoded, type=LoginResult)
    assert decoded == err
    assert isinstance(decoded, LoginError)


def test_tagged_union_discrimination():
    raw = msgspec.json.encode(CredentialLogin(credential=b"x"))
    parsed = msgspec.json.decode(raw)
    assert parsed["type"] == "credential"
