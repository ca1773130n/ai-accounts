import msgspec

from ai_accounts_core.metadata.types import (
    BackendMetadata,
    InstallCheck,
    LoginFlowSpec,
    PlanOption,
)


def test_install_check_shape():
    ic = InstallCheck(command=["claude", "--version"], version_regex=r"(\d+\.\d+\.\d+)")
    assert ic.command == ["claude", "--version"]


def test_login_flow_spec_shape():
    lfs = LoginFlowSpec(
        kind="cli_browser",
        display_name="Sign in with browser",
        description="Opens a browser window to authenticate",
        requires_inputs=[],
    )
    assert lfs.kind == "cli_browser"


def test_plan_option_shape():
    po = PlanOption(id="max", label="Claude Max", description="$200/mo")
    assert po.id == "max"


def test_backend_metadata_roundtrip():
    meta = BackendMetadata(
        kind="claude",
        display_name="Claude Code",
        icon_url=None,
        install_check=InstallCheck(
            command=["claude", "--version"], version_regex=r"(\d+\.\d+\.\d+)"
        ),
        login_flows=[
            LoginFlowSpec(
                kind="cli_browser",
                display_name="Browser",
                description="",
                requires_inputs=[],
            ),
        ],
        plan_options=[PlanOption(id="pro", label="Pro", description="")],
        config_schema={"type": "object", "properties": {"email": {"type": "string"}}},
        supports_multi_account=True,
        isolation_env_var="CLAUDE_CONFIG_DIR",
    )
    data = msgspec.json.encode(meta)
    decoded = msgspec.json.decode(data, type=BackendMetadata)
    assert decoded.kind == "claude"
    assert decoded.supports_multi_account is True
    assert decoded.isolation_env_var == "CLAUDE_CONFIG_DIR"
