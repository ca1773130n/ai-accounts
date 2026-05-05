"""argv-smoke regression test for cliproxyapi flags.

Mirrors tests/backends/test_argv_smoke.py: catches the class of bug where the
wrapper invokes a flag that no longer exists in the installed CLI. The
specific bug this protects against: codex was using ``--codex-login`` (browser
callback flow), which silently fails when the playground is reached via a
remote URL because the OAuth callback hits localhost on the *user's* machine,
not the playground host. The fix is ``--codex-device-login`` (device-code).

If cliproxyapi is not installed, the runtime check is skipped — the source
assertion still runs so drift in the flag_map is always caught.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from ai_accounts_core.cliproxy import manager as cliproxy_manager


def _flag_map_from_source() -> dict[str, str]:
    """Re-derive flag_map by importing and inspecting the function source.

    We don't expose flag_map as a module-level constant (it's defined inside
    start_cliproxy_login), so read it from the source text. This intentionally
    couples the test to the literal — that's the whole point.
    """
    import inspect

    src = inspect.getsource(cliproxy_manager.start_cliproxy_login)
    assert "flag_map" in src, "flag_map definition moved — update this test"
    return {
        "claude": "--claude-login" if '"claude": "--claude-login"' in src else None,
        "codex": "--codex-device-login" if '"codex": "--codex-device-login"' in src else None,
        # cliproxyapi has no separate "--gemini-login" flag; "--login" is
        # the bare Google account login that handles Gemini Code Assist /
        # Gemini Pro subscriptions.
        "gemini": "--login" if '"gemini": "--login"' in src else None,
    }


def test_flag_map_uses_device_login_for_codex() -> None:
    """Source assertion: codex must use the device-code flag, not browser-callback."""
    flag_map = _flag_map_from_source()
    assert flag_map["codex"] == "--codex-device-login", (
        "codex flag drifted away from --codex-device-login. The browser-callback "
        "flow (--codex-login) cannot complete when the playground webui is "
        "reached over a remote URL."
    )
    assert flag_map["claude"] == "--claude-login"
    assert flag_map["gemini"] == "--login", (
        "gemini flag must be --login (the bare Google account flow). "
        "cliproxyapi 6.8.30 has no --gemini-login subcommand."
    )


def test_device_code_regex_captures_codex_45_format() -> None:
    """Codex device codes are 4-5 chars (e.g. FXEJ-GY37O); regex must not truncate.

    Earlier the regex was {4}-?{4} which captured only 'FXEJ-GY37' from
    'FXEJ-GY37O', so the playground showed 8 chars while the OpenAI device
    page expected 9.
    """
    from ai_accounts_core.cliproxy.manager import _DEVICE_CODE_RE

    cases = [
        ("Codex device code: FXEJ-GY37O\n", "FXEJ-GY37O"),  # codex 4-5
        ("Codex device code: FXEJ-GY37O Visit ...", "FXEJ-GY37O"),
        ("code: ABCD-EFGH\n", "ABCD-EFGH"),                 # claude-style 4-4
        ("code: ABCDEFGH\n", "ABCDEFGH"),                   # no dash
    ]
    for text, expected in cases:
        m = _DEVICE_CODE_RE.search(text)
        assert m is not None, f"no match in {text!r}"
        assert m.group(1) == expected, f"{text!r}: got {m.group(1)!r}, want {expected!r}"


def test_cliproxyapi_advertises_codex_device_login() -> None:
    """Installed cliproxyapi must expose -codex-device-login.

    Scoped to codex because that's the flag we just changed. Claude/gemini
    flag advertisement varies across cliproxyapi versions and is a separate
    concern.
    """
    path = shutil.which("cliproxyapi")
    if path is None:
        pytest.skip("cliproxyapi not on PATH")
    proc = subprocess.run([path, "--help"], capture_output=True, timeout=10)
    text = (proc.stdout + proc.stderr).decode(errors="replace")
    assert "-codex-device-login" in text, (
        "cliproxyapi --help does not advertise -codex-device-login — "
        f"subcommand drift!\nfirst 400 chars:\n{text[:400]}"
    )
