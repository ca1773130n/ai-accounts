import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { aiAccountsPlugin } from '@ai-accounts/vue-headless';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import AccountEditForm from '../src/components/AccountEditForm.vue';

const account = {
  id: 'bkd-1',
  kind: 'claude',
  display_name: 'Old name',
  config: { email: 'old@x.y' },
};

const metadata = {
  kind: 'claude',
  display_name: 'Claude Code',
  icon_url: null,
  install_check: { command: [], version_regex: '' },
  login_flows: [],
  plan_options: null,
  config_schema: {
    type: 'object',
    properties: {
      email: { type: 'string' },
    },
  },
  supports_multi_account: true,
  isolation_env_var: 'CLAUDE_CONFIG_DIR',
};

function mkClient(updated: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true, status: 200, statusText: 'OK',
    json: async () => updated,
  } as unknown as Response);
  return new AiAccountsClient({ baseUrl: 'http://t', fetch: fetchMock });
}

describe('AccountEditForm', () => {
  it('renders display_name + schema fields pre-filled', () => {
    const w = mount(AccountEditForm, {
      props: { account, metadata: metadata as never },
      global: { plugins: [[aiAccountsPlugin, { client: mkClient({}) }]] },
    });
    const inputs = w.findAll('input');
    expect((inputs[0]!.element as HTMLInputElement).value).toBe('Old name');
    expect((inputs[1]!.element as HTMLInputElement).value).toBe('old@x.y');
  });

  it('PATCHes updateBackend and emits saved on submit', async () => {
    const updated = { id: 'bkd-1', kind: 'claude', display_name: 'New name', config: { email: 'new@x.y' } };
    const client = mkClient(updated);
    const w = mount(AccountEditForm, {
      props: { account, metadata: metadata as never },
      global: { plugins: [[aiAccountsPlugin, { client }]] },
    });
    const inputs = w.findAll('input');
    await inputs[0]!.setValue('New name');
    await inputs[1]!.setValue('new@x.y');
    await w.find('form').trigger('submit');
    await new Promise((r) => setTimeout(r, 0));
    expect(w.emitted('saved')).toBeTruthy();
    expect((w.emitted('saved')![0]![0] as typeof updated).display_name).toBe('New name');
  });

  it('emits cancel on cancel button click', async () => {
    const w = mount(AccountEditForm, {
      props: { account, metadata: metadata as never },
      global: { plugins: [[aiAccountsPlugin, { client: mkClient({}) }]] },
    });
    const buttons = w.findAll('button');
    const cancelBtn = buttons.find((b) => b.text() === 'Cancel')!;
    await cancelBtn.trigger('click');
    expect(w.emitted('cancel')).toBeTruthy();
  });
});
