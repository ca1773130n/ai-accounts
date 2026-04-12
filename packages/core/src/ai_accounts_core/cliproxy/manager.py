"""CLIProxyAPI install + account-registration helpers.

Scope: just the pieces the wizard needs. Process lifecycle (start/stop/health,
chat routing, config.yaml management) stays in host apps.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import httpx
import msgspec


_CLIPROXY_BINARY = "cliproxyapi"
_CLIPROXY_INSTALL_COMMANDS = [
    ["go", "install", "github.com/router-for-me/CLIProxyAPI/cmd/server@latest"],
    ["brew", "install", "cliproxyapi"],
]

_OAUTH_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_DEVICE_CODE_RE = re.compile(r"code[:\s]+([A-Z0-9]{4}-?[A-Z0-9]{4})", re.IGNORECASE)
_SUCCESS_MARKERS = (
    "Successfully authenticated",
    "Login successful",
    "Authentication successful",
    "Logged in",
    "imported credentials",
)
_FAILURE_MARKERS = ("error:", "failed", "Error")


class CliproxyInstallResult(msgspec.Struct):
    success: bool
    display: str
    stdout: str
    stderr: str
    binary_path: str | None


class CliproxyLoginInfo(msgspec.Struct):
    """Info returned by start_cliproxy_login once the OAuth URL is captured."""

    oauth_url: str | None = None
    device_code: str | None = None
    imported: bool = False
    output: str = ""
    error: str | None = None


def is_cliproxy_installed() -> bool:
    return shutil.which(_CLIPROXY_BINARY) is not None


def get_cliproxy_version() -> str | None:
    path = shutil.which(_CLIPROXY_BINARY)
    if path is None:
        return None
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or result.stderr.strip()
    except Exception:
        pass
    return None


async def install_cliproxy() -> CliproxyInstallResult:
    """Install the cliproxyapi binary. Tries strategies in order."""
    last_stdout = ""
    last_stderr = ""
    last_display = ""
    for argv in _CLIPROXY_INSTALL_COMMANDS:
        if shutil.which(argv[0]) is None:
            continue
        last_display = " ".join(argv)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            last_stdout = stdout.decode(errors="replace")
            last_stderr = stderr.decode(errors="replace")
            if proc.returncode == 0 and is_cliproxy_installed():
                return CliproxyInstallResult(
                    success=True,
                    display=last_display,
                    stdout=last_stdout,
                    stderr=last_stderr,
                    binary_path=shutil.which(_CLIPROXY_BINARY),
                )
        except Exception as exc:  # noqa: BLE001
            last_stderr = f"{last_stderr}\n{exc}"
    return CliproxyInstallResult(
        success=False,
        display=last_display or "(no install command available)",
        stdout=last_stdout,
        stderr=last_stderr,
        binary_path=None,
    )


def _make_fake_open_dir() -> Path:
    """Create a temp dir with a fake ``open`` that writes its URL argument."""
    tmp = Path(tempfile.mkdtemp(prefix="aia-cliproxy-"))
    fake_open = tmp / "open"
    fake_open.write_text(
        '#!/bin/sh\n'
        'echo "$1" > "$(dirname "$0")/captured.url"\n'
        'exit 0\n'
    )
    fake_open.chmod(fake_open.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    xdg = tmp / "xdg-open"
    xdg.symlink_to(fake_open)
    return tmp


async def start_cliproxy_login(
    backend_kind: str,
    config_dir: Path | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[asyncio.subprocess.Process | None, CliproxyLoginInfo]:
    """Spawn ``cliproxyapi --<kind>-login`` and capture the OAuth URL."""
    if not is_cliproxy_installed():
        return None, CliproxyLoginInfo(error="cliproxyapi binary not found")

    flag_map = {
        "claude": "--claude-login",
        "codex": "--codex-login",
        "gemini": "--gemini-login",
    }
    flag = flag_map.get(backend_kind)
    if flag is None:
        return None, CliproxyLoginInfo(error=f"cliproxyapi does not support {backend_kind}")

    fake_dir = _make_fake_open_dir()
    captured_url_path = fake_dir / "captured.url"

    env = dict(os.environ)
    env["PATH"] = f"{fake_dir}:{env.get('PATH', '')}"
    if config_dir is not None:
        env["CLIPROXY_CONFIG_DIR"] = str(config_dir)

    argv = [_CLIPROXY_BINARY, flag]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return None, CliproxyLoginInfo(error="cliproxyapi binary not found")

    output_chunks: list[str] = []
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    url: str | None = None
    device_code: str | None = None
    imported = False

    assert proc.stdout is not None
    while asyncio.get_running_loop().time() < deadline:
        if captured_url_path.exists() and url is None:
            try:
                url = captured_url_path.read_text().strip() or None
            except OSError:
                pass
            if url:
                break

        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.3)
        except asyncio.TimeoutError:
            continue
        if not line:
            break
        text = line.decode(errors="replace")
        output_chunks.append(text)

        if url is None:
            m = _OAUTH_URL_RE.search(text)
            if m:
                url = m.group(0)

        if device_code is None:
            m = _DEVICE_CODE_RE.search(text)
            if m:
                device_code = m.group(1)

        if any(mk in text for mk in _SUCCESS_MARKERS):
            imported = "imported credentials" in text.lower()
            break
        if any(mk in text for mk in _FAILURE_MARKERS):
            break

    info = CliproxyLoginInfo(
        oauth_url=url,
        device_code=device_code,
        imported=imported,
        output="".join(output_chunks),
    )

    if imported:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return None, info

    if url is None and not imported:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        info.error = "could not capture OAuth URL"
        return None, info

    return proc, info


_CLIPROXY_ALLOWED_PORTS = frozenset({54545, 8085})
_CLIPROXY_ALLOWED_PATH_PREFIXES = ("/callback", "/cb", "/oauth")
_CLIPROXY_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1"})


async def forward_cliproxy_callback(callback_url: str) -> dict:
    """Forward an OAuth callback URL to cliproxyapi's local HTTP server."""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(callback_url)
    qs = parse_qs(parsed.query)
    code = qs.get("code", [""])[0]
    state = qs.get("state", [""])[0]
    port = parsed.port or 54545

    # SSRF guard: restrict scheme, host, port, and path
    if parsed.scheme not in ("http", "https"):
        return {"status": "error", "message": "callback URL must use http or https"}
    if parsed.hostname not in _CLIPROXY_ALLOWED_HOSTS:
        return {"status": "error", "message": "callback URL must target localhost"}
    if parsed.port and parsed.port not in _CLIPROXY_ALLOWED_PORTS:
        return {"status": "error", "message": f"callback port {parsed.port} not allowed"}
    if not any(parsed.path.startswith(p) for p in _CLIPROXY_ALLOWED_PATH_PREFIXES):
        return {"status": "error", "message": "callback path not allowed"}

    if not code:
        return {"status": "error", "message": "No 'code' parameter found in URL"}

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
            resp = await http.get(
                f"http://127.0.0.1:{port}{parsed.path}",
                params={"code": code, "state": state},
            )
        if resp.status_code < 400:
            return {"status": "completed", "message": "Callback forwarded successfully"}
        return {
            "status": "error",
            "message": f"Callback server returned {resp.status_code}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to reach callback server: {exc}"}
