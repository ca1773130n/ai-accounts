import { describe, it, expect, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { aiAccountsPlugin } from '@ai-accounts/vue-headless';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import AccountReauth from '../src/components/AccountReauth.vue';

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

const account = { id: 'bkd-1', kind: 'antigravity', display_name: 'me@example.com' };

describe('AccountReauth', () => {
  it('renders a Re-auth button for a registered account', () => {
    const w = mount(AccountReauth, {
      props: { account },
      global: { plugins: [[aiAccountsPlugin, { client: mkClient() }]] },
    });
    expect(w.find('.aia-reauth__btn').text()).toContain('Re-auth');
  });

  it('offers a flow chooser when the backend supports multiple login flows', async () => {
    const meta = [
      {
        kind: 'antigravity',
        display_name: 'Antigravity',
        login_flows: [
          { kind: 'api_key', display_name: 'Google AI Studio key' },
          { kind: 'cli_browser', display_name: 'Antigravity subscription' },
        ],
      },
    ];
    const w = mount(AccountReauth, {
      props: { account },
      global: { plugins: [[aiAccountsPlugin, { client: mkClient(meta) }]] },
    });

    await w.find('.aia-reauth__btn').trigger('click');
    await flushPromises(); // registry.load() resolves -> flow chooser renders

    expect(w.text()).toContain('Sign in via');
    // two backend flows + the Cancel button
    expect(w.findAll('.aia-reauth__flow').length).toBe(3);
  });
});
