import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { aiAccountsPlugin } from '@ai-accounts/vue-headless';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import AccountWizard from '../src/components/AccountWizard.vue';

function mkClient(items: unknown[] = []) {
  return new AiAccountsClient({
    baseUrl: 'http://t',
    fetch: vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ items }),
    } as unknown as Response),
  });
}

describe('AccountWizard', () => {
  it('mounts with aiAccountsPlugin installed', () => {
    const w = mount(AccountWizard, {
      global: { plugins: [[aiAccountsPlugin, { client: mkClient() }]] },
      props: { allowSkip: true },
    });
    expect(w.exists()).toBe(true);
  });

  it('renders BackendPicker when initialBackendKind is not set', async () => {
    const items = [
      {
        kind: 'claude',
        display_name: 'Claude Code',
        icon_url: null,
        install_check: { command: [], version_regex: '' },
        login_flows: [],
        plan_options: null,
        config_schema: {},
        supports_multi_account: true,
        isolation_env_var: 'CLAUDE_CONFIG_DIR',
      },
    ];
    const w = mount(AccountWizard, {
      global: { plugins: [[aiAccountsPlugin, { client: mkClient(items) }]] },
    });
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    await nextTick();
    expect(w.findComponent({ name: 'BackendPicker' }).exists()).toBe(true);
  });

  it('skips picker when initialBackendKind is set', async () => {
    const items = [
      {
        kind: 'claude',
        display_name: 'Claude Code',
        icon_url: null,
        install_check: { command: [], version_regex: '' },
        login_flows: [
          {
            kind: 'cli_browser',
            display_name: 'Browser',
            description: '',
            requires_inputs: [],
          },
        ],
        plan_options: null,
        config_schema: {},
        supports_multi_account: true,
        isolation_env_var: 'CLAUDE_CONFIG_DIR',
      },
    ];
    const w = mount(AccountWizard, {
      props: { initialBackendKind: 'claude' },
      global: { plugins: [[aiAccountsPlugin, { client: mkClient(items) }]] },
    });
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    await nextTick();
    expect(w.findComponent({ name: 'BackendPicker' }).exists()).toBe(false);
  });
});
