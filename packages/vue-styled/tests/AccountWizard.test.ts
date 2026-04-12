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

function mkRoutingClient() {
  // Fetch mock that returns different bodies based on URL so the wizard's
  // mount-time calls (backends/_meta, cliproxy/status) both succeed.
  const fetchMock = vi.fn().mockImplementation(async (url: string) => {
    if (typeof url === 'string' && url.includes('/cliproxy/status')) {
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({
          installed: false,
          version: null,
          binary_path: null,
        }),
      } as unknown as Response;
    }
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ items: [] }),
    } as unknown as Response;
  });
  const client = new AiAccountsClient({ baseUrl: 'http://t', fetch: fetchMock });
  return { client, fetchMock };
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

  it('queries /cliproxy/status on mount', async () => {
    const { client, fetchMock } = mkRoutingClient();
    const w = mount(AccountWizard, {
      props: { initialBackendKind: 'claude' },
      global: { plugins: [[aiAccountsPlugin, { client }]] },
    });
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    await nextTick();
    const urls = fetchMock.mock.calls.map((c) => c[0] as string);
    expect(urls.some((u) => u.includes('/api/v1/cliproxy/status'))).toBe(true);
    expect(w.exists()).toBe(true);
  });

  it('mounts successfully for proxy-supported backend (claude)', async () => {
    const { client } = mkRoutingClient();
    const w = mount(AccountWizard, {
      props: { initialBackendKind: 'claude' },
      global: { plugins: [[aiAccountsPlugin, { client }]] },
    });
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    // The wizard should render without throwing — the proxy step is
    // available in the step machine but not shown yet (we're on step 1).
    expect(w.exists()).toBe(true);
    expect(w.html()).toContain('Subscription');
  });
});
