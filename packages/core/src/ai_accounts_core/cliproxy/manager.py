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
# Codex device codes are 4-5 alphanumeric (e.g. "FXEJ-GY37O" — 9 chars total
# excluding the dash). Claude/older formats are 4-4 (8 chars). Allow the
# second group to be 4-8 chars so both fit; greedy matching naturally takes
# the longest run, so we don't truncate the trailing character of a 4-5 code.
_DEVICE_CODE_RE = re.compile(r"code[:\s]+([A-Z0-9]{4}-?[A-Z0-9]{4,8})", re.IGNORECASE)
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
    fake_dir: str | None = None


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

    # Codex uses the device-code flow (URL + code printed to stdout) rather
    # than the browser-callback flow (--codex-login). Device-code works
    # unchanged when the playground is reached over a remote URL — the
    # callback flow does not, because the OAuth provider would redirect to
    # localhost on the *user's* machine, not the playground host.
    flag_map = {
        "claude": "--claude-login",
        "codex": "--codex-device-login",
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
        shutil.rmtree(fake_dir, ignore_errors=True)
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
        shutil.rmtree(fake_dir, ignore_errors=True)
        return None, info

    if url is None and not imported:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        shutil.rmtree(fake_dir, ignore_errors=True)
        info.error = "could not capture OAuth URL"
        return None, info

    info.fake_dir = str(fake_dir)
    return proc, info


# Allowed local callback ports for cliproxyapi's OAuth registration. The
# allowlist is an SSRF guard around the upstream HTTP forward. Extend as
# new cliproxyapi versions / providers add ports:
#   54545, 8085 — historical cliproxyapi defaults
#   1455        — cliproxyapi 0.16+ uses the same port as Codex's
#                 codex_cli_simplified_flow (shares OAuth client app id)
_CLIPROXY_ALLOWED_PORTS = frozenset({1455, 8085, 54545})
# Allowed callback path prefixes. cliproxyapi 0.16+ uses /auth/callback
# (matches Codex's codex_cli_simplified_flow); older versions used /callback.
_CLIPROXY_ALLOWED_PATH_PREFIXES = ("/auth/callback", "/callback", "/cb", "/oauth")
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
    effective_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if effective_port not in _CLIPROXY_ALLOWED_PORTS:
        return {"status": "error", "message": f"callback port {effective_port} not allowed"}
    # Path allowlist: reject URL-encoded ".." traversal and non-allowed prefixes.
    # We check the RAW path (urlparse already URL-decodes %2F, but %2E.%2E
    # remains as ".." — explicit reject) and we also assert no segment is "..".
    raw_path = parsed.path or "/"
    if "/.." in raw_path or raw_path.endswith("/..") or "%2e%2e" in raw_path.lower():
        return {"status": "error", "message": "callback path contains traversal"}
    # Split into segments and refuse "." / ".." or empty segments mid-path.
    from pathlib import PurePosixPath as _Path
    parts = _Path(raw_path).parts
    if any(p in ("..", ".") for p in parts):
        return {"status": "error", "message": "callback path contains traversal"}
    if not any(raw_path.startswith(p) for p in _CLIPROXY_ALLOWED_PATH_PREFIXES):
        return {"status": "error", "message": "callback path not allowed"}

    if not code:
        return {"status": "error", "message": "No 'code' parameter found in URL"}

    # Forward to the local callback server. Claude CLI v2.1.92+ binds its
    # callback server to the IPv6 loopback ([::1]) on macOS when the system
    # prefers IPv6, so we try IPv6 first and then fall back to IPv4 + plain
    # hostname. cliproxyapi still listens on 127.0.0.1, so order matters:
    # the first reachable host wins.
    last_error: str | None = None
    last_status: int | None = None
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
        for host in ("[::1]", "127.0.0.1", "localhost"):
            try:
                resp = await http.get(
                    f"http://{host}:{port}{parsed.path}",
                    params={"code": code, "state": state},
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            if resp.status_code < 400:
                return {
                    "status": "completed",
                    "message": "Callback forwarded successfully",
                }
            last_status = resp.status_code
    if last_status is not None:
        return {
            "status": "error",
            "message": f"Callback server returned {last_status}",
        }
    return {
        "status": "error",
        "message": f"Failed to reach callback server: {last_error or 'unknown error'}",
    }


_CLIPROXY_CONFIG = Path.home() / ".cli-proxy-api" / "config.yaml"


def detect_cliproxy() -> tuple[str, str] | None:
    """Auto-detect a running CLIProxyAPI from ~/.cli-proxy-api/config.yaml.

    Returns (base_url, api_key) if reachable, else None.
    """
    if not _CLIPROXY_CONFIG.exists():
        return None
    try:
        text = _CLIPROXY_CONFIG.read_text()
        # Simple YAML parsing — avoid pyyaml dependency
        port = 8317
        api_key = "not-needed"
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("port:"):
                try:
                    port = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("- ") and api_key == "not-needed":
                # First item under api-keys list
                api_key = line[2:].strip().strip('"').strip("'")
    except Exception:
        return None
    base_url = f"http://127.0.0.1:{port}/v1"
    try:
        resp = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=2,
        )
        if resp.status_code == 200:
            return base_url, api_key
    except Exception:
        pass
    return None


def _parse_config() -> tuple[int, str]:
    """Read port and api-key from ~/.cli-proxy-api/config.yaml."""
    port = 8317
    api_key = "not-needed"
    if _CLIPROXY_CONFIG.exists():
        for line in _CLIPROXY_CONFIG.read_text().splitlines():
            line = line.strip()
            if line.startswith("port:"):
                try:
                    port = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("- ") and api_key == "not-needed":
                api_key = line[2:].strip().strip('"').strip("'")
    return port, api_key


def _check_healthy(port: int, api_key: str) -> bool:
    """Check if CLIProxyAPI responds on the given port."""
    try:
        resp = httpx.get(
            f"http://127.0.0.1:{port}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=2,
        )
        return resp.status_code == 200
    except Exception:
        return False


def write_cliproxy_config(port: int = 8317, api_key: str = "not-needed") -> Path:
    """Write ~/.cli-proxy-api/config.yaml with the given port and api-key.

    Creates the directory if needed. Returns the config path.

    cliproxyapi 6.8.30+ requires an explicit ``auth-dir`` config entry —
    without it the binary tries to ``mkdir("")`` and exits with
    ``failed to create auth directory`` before opening the listen port,
    which presents to callers as a 10s readiness timeout.

    The ``auth-dir`` MUST point at the same directory where cliproxyapi's
    own login flows write credential files (e.g. ``codex-<email>.json``,
    ``claude-<email>.json``). cliproxyapi's login subcommands write those
    files into the config directory itself, NOT into a subdirectory — so
    pointing ``auth-dir`` at an ``auth/`` subdir leaves cliproxyapi with
    zero providers ("unknown provider for model …" on every chat). Use
    the config directory as the auth directory so the server scans the
    same files the login flow created.
    """
    auth_dir = _CLIPROXY_CONFIG.parent
    auth_dir.mkdir(parents=True, exist_ok=True)
    _CLIPROXY_CONFIG.write_text(
        f"port: {port}\n"
        f'auth-dir: "{auth_dir}"\n'
        f"api-keys:\n"
        f'  - "{api_key}"\n'
    )
    return _CLIPROXY_CONFIG


def start_cliproxy_server(
    port: int = 8317,
    api_key: str = "not-needed",
) -> dict:
    """Start CLIProxyAPI as a background process.

    Writes config, checks if already running, starts the binary,
    waits up to 10s for readiness.

    Returns:
        {"status": "ok"|"error", "port": int, "pid": int|None, "message": str}
    """
    import signal as _signal
    import time as _time

    if not is_cliproxy_installed():
        return {"status": "error", "port": port, "pid": None, "message": "cliproxyapi not installed"}

    write_cliproxy_config(port, api_key)

    if _check_healthy(port, api_key):
        return {"status": "ok", "port": port, "pid": None, "message": "already running"}

    config_path = str(_CLIPROXY_CONFIG)
    stderr_path = Path(tempfile.mktemp(suffix="-cliproxy-stderr.log"))
    try:
        stderr_file = open(stderr_path, "w")
        proc = subprocess.Popen(
            [_CLIPROXY_BINARY, "--config", config_path],
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            start_new_session=True,
        )
    except FileNotFoundError:
        return {"status": "error", "port": port, "pid": None, "message": "cliproxyapi binary not found"}
    except Exception as exc:
        return {"status": "error", "port": port, "pid": None, "message": str(exc)}

    deadline = _time.monotonic() + 10
    while _time.monotonic() < deadline:
        if _check_healthy(port, api_key):
            stderr_file.close()
            stderr_path.unlink(missing_ok=True)
            return {"status": "ok", "port": port, "pid": proc.pid, "message": f"started on port {port}"}
        _time.sleep(0.5)

    # Timeout — capture stderr for diagnostics
    stderr_file.close()
    stderr_content = ""
    try:
        stderr_content = stderr_path.read_text(errors="replace")[-500:]
    except Exception:
        pass
    stderr_path.unlink(missing_ok=True)

    try:
        os.killpg(os.getpgid(proc.pid), _signal.SIGTERM)
        proc.wait(timeout=3)
    except Exception:
        pass
    msg = "did not become ready within 10s"
    if stderr_content.strip():
        msg += f". stderr: {stderr_content.strip()}"
    return {"status": "error", "port": port, "pid": None, "message": msg}


def stop_cliproxy_server() -> dict:
    """Stop any running CLIProxyAPI process.

    Returns {"status": "ok"|"error", "message": str}
    """
    try:
        subprocess.run(["pkill", "-f", _CLIPROXY_BINARY], capture_output=True, timeout=5)
        return {"status": "ok", "message": "stopped"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def cliproxy_server_status() -> dict:
    """Check CLIProxyAPI server status.

    Returns {"installed": bool, "running": bool, "port": int, "version": str|None}
    """
    port, api_key = _parse_config()
    return {
        "installed": is_cliproxy_installed(),
        "running": _check_healthy(port, api_key),
        "port": port,
        "version": get_cliproxy_version(),
    }
