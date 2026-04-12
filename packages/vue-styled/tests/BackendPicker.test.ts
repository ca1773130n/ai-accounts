import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { aiAccountsPlugin } from '@ai-accounts/vue-headless';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import BackendPicker from '../src/components/BackendPicker.vue';

const items = [
  { kind: 'claude', display_name: 'Claude Code', icon_url: null,
    install_check: { command: [], version_regex: '' }, login_flows: [],
    plan_options: null, config_schema: {}, supports_multi_account: true,
    isolation_env_var: 'CLAUDE_CONFIG_DIR' },
  { kind: 'codex', display_name: 'Codex', icon_url: null,
    install_check: { command: [], version_regex: '' }, login_flows: [],
    plan_options: null, config_schema: {}, supports_multi_account: true,
    isolation_env_var: 'CODEX_HOME' },
];

function mkClient() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true, status: 200, statusText: 'OK',
    json: async () => ({ items }),
  } as unknown as Response);
  return new AiAccountsClient({ baseUrl: 'http://t', fetch: fetchMock });
}

describe('BackendPicker', () => {
  it('renders registered backends after mount', async () => {
    const w = mount(BackendPicker, {
      global: { plugins: [[aiAccountsPlugin, { client: mkClient() }]] },
    });
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    await nextTick();
    expect(w.text()).toContain('Claude Code');
    expect(w.text()).toContain('Codex');
  });

  it('emits pick with kind', async () => {
    const w = mount(BackendPicker, {
      global: { plugins: [[aiAccountsPlugin, { client: mkClient() }]] },
    });
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    await nextTick();
    const buttons = w.findAll('button');
    await buttons[0].trigger('click');
    expect(w.emitted('pick')).toBeTruthy();
    expect(w.emitted('pick')![0]).toEqual(['claude']);
  });

  it('shows installed badge when installStatus provided', async () => {
    const w = mount(BackendPicker, {
      global: { plugins: [[aiAccountsPlugin, { client: mkClient() }]] },
      props: {
        installStatus: {
          claude: { installed: true, version: '1.2.3' },
          codex: { installed: false, version: null },
        },
      },
    });
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    await nextTick();
    expect(w.text()).toContain('installed v1.2.3');
    expect(w.text()).toContain('not detected');
  });
});
