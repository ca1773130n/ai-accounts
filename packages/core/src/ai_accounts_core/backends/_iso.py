"""Helper for absolute, mkdir-on-touch isolation directories.

CLI subprocesses inherit our cwd via ``CliOrchestrator(cwd=...)``. If the
isolation_dir is RELATIVE, the child resolves env vars like CODEX_HOME
against its own (just-chdir'd) cwd, which DOUBLES the relative path
("backend_dirs/<id>/backend_dirs/<id>"). Always resolve to absolute and
ensure the directory exists before any subprocess uses it.
"""

from __future__ import annotations

import contextlib
from pathlib import Path


def resolved_iso(path: Path) -> Path:
    """Return an absolute Path to ``path`` and ensure the directory exists."""
    abs_path = path.resolve()
    abs_path.mkdir(parents=True, exist_ok=True)
    # 0o700 so per-account secrets written under here (goose secrets.yaml,
    # crush.json) aren't world-readable. Best-effort: some filesystems reject chmod.
    with contextlib.suppress(OSError):
        abs_path.chmod(0o700)
    return abs_path
