"""Shared base class for CLI-backed backends.

Pulls out the parts that were copy-pasted four times across
``claude.py``, ``codex.py``, ``gemini.py``, ``opencode.py``:

- ``_run`` — wrapper around the asyncio subprocess spawn helper returning
  ``(returncode, stdout, stderr)``.
- ``detect`` — ``shutil.which(_CLI_NAME)`` + ``<cli> --version`` parse.

Subclasses override ``_CLI_NAME`` to declare the binary they wrap. Anything
that differs across backends (validate, list_models, chat, get_usage, pty)
stays in the subclass — the protocol is already minimal enough that
forcing a uniform shape onto those would hide real per-CLI quirks
(macOS keychain, codex login-status text, etc).
"""

from __future__ import annotations

import shutil
from asyncio import create_subprocess_exec as _spawn_subprocess
from asyncio import subprocess as _async_subprocess
from typing import Any, ClassVar

from ai_accounts_core.domain.backend import DetectResult


class CliBackendBase:
    """Mixin for backends that wrap a local CLI tool."""

    _CLI_NAME: ClassVar[str] = ""

    async def _run(self, spec: dict[str, Any]) -> tuple[int, bytes, bytes]:
        argv: list[str] = spec["argv"]
        env: dict[str, str] | None = spec.get("env")
        proc = await _spawn_subprocess(
            *argv,
            stdout=_async_subprocess.PIPE,
            stderr=_async_subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout, stderr

    async def detect(self) -> DetectResult:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return DetectResult(installed=False)
        rc, stdout, _stderr = await self._run({"argv": [path, "--version"]})
        if rc != 0:
            return DetectResult(installed=True, path=path, notes="version check failed")
        version: str | None = None
        if stdout:
            first_line = stdout.decode(errors="replace").strip().splitlines()[0]
            version = first_line or None
        return DetectResult(installed=True, version=version, path=path)
