"""Unit tests for cliproxy/manager.py — mocked subprocess & shutil."""

from __future__ import annotations

import stat
from unittest.mock import patch

from ai_accounts_core.cliproxy.manager import (
    CliproxyLoginInfo,
    _make_fake_open_dir,
    forward_cliproxy_callback,
    is_cliproxy_installed,
    start_cliproxy_login,
)


def test_make_fake_open_dir_creates_executable():
    """_make_fake_open_dir creates an executable 'open' script with expected content."""
    tmp = _make_fake_open_dir()
    fake_open = tmp / "open"
    assert fake_open.exists(), "open script not created"
    mode = fake_open.stat().st_mode
    assert mode & stat.S_IEXEC, "open script not executable"
    content = fake_open.read_text()
    assert "#!/bin/sh" in content
    assert "captured.url" in content
    # xdg-open symlink should also exist
    xdg = tmp / "xdg-open"
    assert xdg.exists()
    assert xdg.is_symlink()


def test_is_cliproxy_installed_returns_bool():
    """is_cliproxy_installed returns a bool regardless of system state."""
    result = is_cliproxy_installed()
    assert isinstance(result, bool)


async def test_start_cliproxy_login_not_installed():
    """When cliproxyapi is not on PATH, returns (None, error info)."""
    with patch("ai_accounts_core.cliproxy.manager.shutil") as mock_shutil:
        mock_shutil.which.return_value = None
        proc, info = await start_cliproxy_login("claude")
    assert proc is None
    assert isinstance(info, CliproxyLoginInfo)
    assert info.error is not None
    assert "not found" in info.error


async def test_start_cliproxy_login_unsupported_kind():
    """Unsupported backend kind returns an error about the kind."""
    with patch("ai_accounts_core.cliproxy.manager.shutil") as mock_shutil:
        mock_shutil.which.return_value = "/usr/local/bin/cliproxyapi"
        proc, info = await start_cliproxy_login("martian")
    assert proc is None
    assert isinstance(info, CliproxyLoginInfo)
    assert info.error is not None
    assert "martian" in info.error


async def test_forward_callback_validates_port_54545():
    """Port 54545 passes SSRF validation (failure is connection, not validation)."""
    result = await forward_cliproxy_callback(
        "http://localhost:54545/callback?code=testcode&state=teststate"
    )
    # Should pass validation and fail at httpx connect
    assert result["status"] == "error"
    assert "reach" in result["message"].lower() or "connect" in result["message"].lower()
