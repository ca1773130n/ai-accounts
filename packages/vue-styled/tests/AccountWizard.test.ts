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
    expect(w.html()).toContain('account?');
  });

  it('renders a collapsed 3-phase step indicator', async () => {
    const { client } = mkRoutingClient();
    const w = mount(AccountWizard, {
      props: { initialBackendKind: 'claude' },
      global: { plugins: [[aiAccountsPlugin, { client }]] },
    });
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    await nextTick();
    // The indicator collapses the 5 internal steps into 3 displayed phases:
    // Setup / Login / Finish.
    const dots = w.findAll('.wizard-steps .step-indicator');
    expect(dots).toHaveLength(3);
    const labels = w.findAll('.wizard-steps .step-label').map((l) => l.text());
    expect(labels).toEqual(['Setup', 'Login', 'Finish']);
  });

  it('does not show a config-path input on the CLI step by default', async () => {
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
    // Advance to the CLI step (internal step 2) without going through the
    // subscription radio — the path override now lives behind an <details>
    // "Advanced" toggle that is collapsed by default, so no bare text input
    // is rendered in the cli step body up front.
    (w.vm as unknown as { currentStep: string }).currentStep = 'cli';
    await nextTick();
    await nextTick();
    const advanced = w.find('details.config-advanced');
    expect(advanced.exists()).toBe(true);
    // Collapsed <details> means the override input is not open for editing.
    expect(advanced.attributes('open')).toBeUndefined();
  });

  it('maps deepseek/qwen to keyless API-key env prefixes', async () => {
    const { client } = mkRoutingClient();
    const w = mount(AccountWizard, {
      props: { initialBackendKind: 'deepseek' },
      global: { plugins: [[aiAccountsPlugin, { client }]] },
    });
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    const vm = w.vm as unknown as {
      backendKind: string;
      accountName: string;
      apiKeyEnv: string;
      requiresNoCli: boolean;
    };
    vm.accountName = 'work';
    await nextTick();
    expect(vm.apiKeyEnv).toBe('DEEPSEEK_API_KEY_WORK');
    expect(vm.requiresNoCli).toBe(true);

    vm.backendKind = 'qwen';
    await nextTick();
    expect(vm.apiKeyEnv).toBe('DASHSCOPE_API_KEY_WORK');
    expect(vm.requiresNoCli).toBe(true);
  });

  it('treats goose/aider/crush as CLI backends with a goose config dir', async () => {
    const { client } = mkRoutingClient();
    const w = mount(AccountWizard, {
      props: { initialBackendKind: 'goose' },
      global: { plugins: [[aiAccountsPlugin, { client }]] },
    });
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    const vm = w.vm as unknown as {
      backendKind: string;
      configPath: string;
      requiresNoCli: boolean;
    };
    await nextTick();
    expect(vm.requiresNoCli).toBe(false);
    expect(vm.configPath).toBe('~/.config/goose');

    vm.backendKind = 'aider';
    await nextTick();
    expect(vm.requiresNoCli).toBe(false);

    vm.backendKind = 'crush';
    await nextTick();
    expect(vm.requiresNoCli).toBe(false);
  });
});
