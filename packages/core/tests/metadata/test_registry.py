import pytest
from ai_accounts_core.metadata.registry import BackendRegistry
from ai_accounts_core.metadata.types import (
    BackendMetadata,
    InstallCheck,
    LoginFlowSpec,
)


def _meta(kind: str) -> BackendMetadata:
    return BackendMetadata(
        kind=kind,
        display_name=kind.title(),
        icon_url=None,
        install_check=InstallCheck(command=[kind, "--version"], version_regex=r"(\d+)"),
        login_flows=[
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="",
                requires_inputs=[],
            )
        ],
        plan_options=None,
        config_schema={"type": "object"},
        supports_multi_account=True,
        isolation_env_var=None,
    )


def test_register_and_list():
    reg = BackendRegistry()
    reg.register(_meta("claude"))
    reg.register(_meta("codex"))
    assert [m.kind for m in reg.list()] == ["claude", "codex"]


def test_register_duplicate_raises():
    reg = BackendRegistry()
    reg.register(_meta("claude"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_meta("claude"))


def test_get_by_kind():
    reg = BackendRegistry()
    reg.register(_meta("gemini"))
    assert reg.get("gemini").display_name == "Gemini"


def test_get_missing_raises():
    reg = BackendRegistry()
    with pytest.raises(KeyError):
        reg.get("martian")
