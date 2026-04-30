from pathlib import Path

from ai_accounts_core.backends._iso import resolved_iso


def test_resolves_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rel = Path("backend_dirs/bkd-abc")
    out = resolved_iso(rel)
    assert out.is_absolute()
    assert out == (tmp_path / "backend_dirs/bkd-abc").resolve()


def test_creates_dir(tmp_path):
    target = tmp_path / "x" / "y" / "z"
    assert not target.exists()
    out = resolved_iso(target)
    assert out.is_dir()
    assert out == target.resolve()


def test_idempotent(tmp_path):
    target = tmp_path / "z"
    out1 = resolved_iso(target)
    out2 = resolved_iso(target)
    assert out1 == out2
