"""Helper for absolute, mkdir-on-touch isolation directories.

CLI subprocesses inherit our cwd via ``CliOrchestrator(cwd=...)``. If the
isolation_dir is RELATIVE, the child resolves env vars like CODEX_HOME
against its own (just-chdir'd) cwd, which DOUBLES the relative path
("backend_dirs/<id>/backend_dirs/<id>"). Always resolve to absolute and
ensure the directory exists before any subprocess uses it.
"""

from __future__ import annotations

from pathlib import Path


def resolved_iso(path: Path) -> Path:
    """Return an absolute Path to ``path`` and ensure the directory exists."""
    abs_path = path.resolve()
    abs_path.mkdir(parents=True, exist_ok=True)
    return abs_path
