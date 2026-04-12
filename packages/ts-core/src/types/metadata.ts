export type InstallCheck = {
  command: string[];
  version_regex: string;
};

export type InputSpec = {
  name: string;
  label: string;
  kind: 'text' | 'secret' | 'email' | 'path';
  placeholder?: string | null;
};

export type LoginFlowSpec = {
  kind: string;
  display_name: string;
  description: string;
  requires_inputs: InputSpec[];
};

export type PlanOption = {
  id: string;
  label: string;
  description: string;
};

export type BackendMetadata = {
  kind: string;
  display_name: string;
  icon_url: string | null;
  install_check: InstallCheck;
  login_flows: LoginFlowSpec[];
  plan_options: PlanOption[] | null;
  config_schema: Record<string, unknown>;
  supports_multi_account: boolean;
  isolation_env_var: string | null;
};
