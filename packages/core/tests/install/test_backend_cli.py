import pytest

from ai_accounts_core.install import get_install_strategies, install_backend_cli


def test_install_strategies_registered_for_core_kinds():
    for kind in ("claude", "codex", "gemini", "opencode"):
        strategies = get_install_strategies(kind)
        assert len(strategies) >= 1
        assert strategies[0].argv[0] == "npm"


def test_unknown_kind_returns_empty():
    assert get_install_strategies("martian") == []


async def test_install_unknown_kind_raises():
    with pytest.raises(ValueError, match="no install strategy"):
        await install_backend_cli("martian")
