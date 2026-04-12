import { describe, it, expect } from 'vitest';
import type {
  LoginEvent,
  LoginComplete,
  PromptAnswer,
  UrlPrompt,
  LoginFlowKind,
} from '../src/types/login';
import type { BackendMetadata } from '../src/types/metadata';
import type { AiAccountsEvent } from '../src/events';

describe('login types', () => {
  it('UrlPrompt has required fields', () => {
    const e: UrlPrompt = { type: 'url_prompt', prompt_id: 'p', url: 'https://x' };
    expect(e.type).toBe('url_prompt');
  });

  it('LoginEvent narrows correctly', () => {
    const e: LoginEvent = { type: 'complete', account_id: 'bkd-1', backend_status: 'validating' };
    if (e.type === 'complete') {
      const c: LoginComplete = e;
      expect(c.account_id).toBe('bkd-1');
    }
  });

  it('PromptAnswer shape', () => {
    const a: PromptAnswer = { prompt_id: 'p', answer: 'x' };
    expect(a.prompt_id).toBe('p');
  });

  it('LoginFlowKind is union of three strings', () => {
    const a: LoginFlowKind = 'api_key';
    const b: LoginFlowKind = 'oauth_device';
    const c: LoginFlowKind = 'cli_browser';
    expect([a, b, c]).toEqual(['api_key', 'oauth_device', 'cli_browser']);
  });
});

describe('metadata types', () => {
  it('BackendMetadata shape', () => {
    const m: BackendMetadata = {
      kind: 'claude',
      display_name: 'Claude',
      icon_url: null,
      install_check: { command: ['claude', '--version'], version_regex: '(\\d+)' },
      login_flows: [],
      plan_options: null,
      config_schema: {},
      supports_multi_account: true,
      isolation_env_var: 'CLAUDE_CONFIG_DIR',
    };
    expect(m.kind).toBe('claude');
  });
});

describe('AiAccountsEvent', () => {
  it('includes wizard + login variants', () => {
    const e1: AiAccountsEvent = { type: 'wizard.opened', backendKind: 'claude' };
    const e2: AiAccountsEvent = { type: 'login.completed', sessionId: 's', accountId: 'a' };
    expect(e1.type).toBe('wizard.opened');
    expect(e2.type).toBe('login.completed');
  });
});
