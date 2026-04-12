"""Backend metadata — the shape served at GET /api/v1/backends/_meta."""

from __future__ import annotations

import msgspec


class InstallCheck(msgspec.Struct):
    """How to verify a backend CLI is installed and extract its version."""

    command: list[str]
    version_regex: str


class InputSpec(msgspec.Struct):
    """One required field for a login flow (e.g. API key, email)."""

    name: str
    label: str
    kind: str = "text"  # "text" | "secret" | "email" | "path"
    placeholder: str | None = None


class LoginFlowSpec(msgspec.Struct):
    kind: str  # "api_key" | "oauth_device" | "cli_browser"
    display_name: str
    description: str
    requires_inputs: list[InputSpec] = []


class PlanOption(msgspec.Struct):
    id: str
    label: str
    description: str


class BackendMetadata(msgspec.Struct):
    kind: str
    display_name: str
    icon_url: str | None
    install_check: InstallCheck
    login_flows: list[LoginFlowSpec]
    plan_options: list[PlanOption] | None
    config_schema: dict
    supports_multi_account: bool
    isolation_env_var: str | None
