"""Shared base class for CLI-backed backends.

Pulls out the parts that were copy-pasted four times across
``claude.py``, ``codex.py``, ``antigravity.py``, ``opencode.py``:

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

import logging
import shutil
from asyncio import create_subprocess_exec as _spawn_subprocess
from asyncio import subprocess as _async_subprocess
from typing import Any, ClassVar

from ai_accounts_core.domain.backend import DetectResult


def warn_empty_usage_parse(logger: logging.Logger, backend: str, data: object) -> None:
    """Log that a 200 response yielded no usage windows, and what it held.

    A ``get_usage`` that returns ``[]`` is ambiguous: it means "this account
    has nothing to report" AND "the endpoint changed shape and every key we
    read is missing". Twelve backends define ``get_usage`` and all of them
    collapse both cases to the same empty list.

    That ambiguity is not theoretical. The codex parser read a top-level
    ``rate_limits`` list that ``chatgpt.com/backend-api/wham/usage`` has never
    returned, so every single call parsed to ``[]`` — for months, silently,
    because an empty list is exactly what a quiet account looks like. Its
    matching test mocked the invented keys, so the suite stayed green
    throughout. The claude parser is suspected of the same defect and cannot
    be checked without an Anthropic credential.

    Logging the keys the endpoint ACTUALLY returned turns the next occurrence
    into a one-line fix instead of a rediscovery. Only the top-level key names
    are emitted — never values, which carry quota figures and, depending on
    the provider, account identifiers.
    """
    if isinstance(data, dict):
        shape = ", ".join(sorted(map(str, data.keys()))) or "(no keys)"
    else:
        shape = f"(not an object: {type(data).__name__})"
    logger.warning(
        "%s get_usage: HTTP 200 but no usage windows parsed. The response "
        "carried these top-level keys: %s. If they are not the ones this "
        "parser reads, the endpoint's shape has changed and usage has been "
        "silently reported as empty.",
        backend,
        shape,
    )


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
