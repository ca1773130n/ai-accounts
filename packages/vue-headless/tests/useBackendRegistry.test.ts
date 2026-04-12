import { describe, it, expect, vi } from 'vitest';
import { createApp, defineComponent, h } from 'vue';
import { aiAccountsPlugin } from '../src/plugin';
import { useBackendRegistry } from '../src/composables/useBackendRegistry';
import { AiAccountsClient } from '@ai-accounts/ts-core';

const mkClient = (items: unknown[]) => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => ({ items }),
  } as unknown as Response);
  return new AiAccountsClient({ baseUrl: 'http://t', fetch: fetchMock });
};

function mountWithRegistry(client: AiAccountsClient) {
  let captured: ReturnType<typeof useBackendRegistry> | null = null;
  const Child = defineComponent({
    setup() {
      captured = useBackendRegistry();
      return () => h('div');
    },
  });
  const app = createApp(Child);
  app.use(aiAccountsPlugin, { client });
  app.mount(document.createElement('div'));
  return captured!;
}

describe('useBackendRegistry', () => {
  it('fetches /_meta and populates reactive list', async () => {
    const items = [
      {
        kind: 'claude',
        display_name: 'Claude',
        icon_url: null,
        install_check: { command: ['claude'], version_regex: '(\\d)' },
        login_flows: [],
        plan_options: null,
        config_schema: {},
        supports_multi_account: true,
        isolation_env_var: 'CLAUDE_CONFIG_DIR',
      },
    ];
    const registry = mountWithRegistry(mkClient(items));
    await registry.load();
    expect(registry.backends.value).toHaveLength(1);
    expect(registry.get('claude')?.display_name).toBe('Claude');
    expect(registry.loaded.value).toBe(true);
  });

  it('returns undefined for unknown kind', async () => {
    const registry = mountWithRegistry(mkClient([]));
    await registry.load();
    expect(registry.get('martian')).toBeUndefined();
  });
});
