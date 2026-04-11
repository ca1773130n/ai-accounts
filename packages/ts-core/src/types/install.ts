/**
 * Types for backend CLI install + CLIProxyAPI install/login flows.
 *
 * Mirror of Python models in `ai_accounts.core.cli_install` /
 * `ai_accounts.core.cliproxy_manager` and the Litestar route responses.
 */

export type InstallResult = {
  kind: string;
  success: boolean;
  display: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  binary_path: string | null;
};

export type CliproxyStatus = {
  installed: boolean;
  version: string | null;
  binary_path: string | null;
};

export type CliproxyInstallResult = {
  success: boolean;
  display: string;
  stdout: string;
  stderr: string;
  binary_path: string | null;
};

export type CliproxyLoginBeginResponse = {
  status: 'started' | 'imported' | 'skipped' | 'error';
  message: string;
  oauth_url?: string | null;
  device_code?: string | null;
};

export type CliproxyCallbackForwardResponse = {
  status: 'completed' | 'error';
  message: string;
};
