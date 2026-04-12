import { describe, it, expect, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import { aiAccountsPlugin } from '../src/plugin';
import { useLoginSession } from '../src/composables/useLoginSession';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import type { LoginEvent } from '@ai-accounts/ts-core';

function mockClient(events: LoginEvent[]) {
  const client = new AiAccountsClient({ baseUrl: 'http://t', fetch: vi.fn() });
  (client as unknown as { beginLogin: unknown }).beginLogin = vi
    .fn()
    .mockResolvedValue({ session_id: 'sess-1' });
  (client as unknown as { streamLogin: unknown }).streamLogin = async function* () {
    for (const e of events) yield e;
  };
  (client as unknown as { respondLogin: unknown }).respondLogin = vi
    .fn()
    .mockResolvedValue(undefined);
  (client as unknown as { cancelLogin: unknown }).cancelLogin = vi
    .fn()
    .mockResolvedValue(undefined);
  return client;
}

describe('useLoginSession', () => {
  it('transitions through text_prompt → complete', async () => {
    const events: LoginEvent[] = [
      { type: 'text_prompt', prompt_id: 'p', prompt: 'key', hidden: true },
      { type: 'complete', account_id: 'bkd-1', backend_status: 'validating' },
    ];
    let captured: ReturnType<typeof useLoginSession> | null = null;
    const Child = defineComponent({
      setup() {
        captured = useLoginSession();
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: mockClient(events) });
    app.mount(document.createElement('div'));

    await captured!.start('bkd-1', 'api_key', {});
    await nextTick();
    expect(captured!.status.value).toBe('complete');
    expect(captured!.accountId.value).toBe('bkd-1');
  });

  it('captures url_prompt', async () => {
    const events: LoginEvent[] = [
      { type: 'url_prompt', prompt_id: 'u', url: 'https://x', user_code: 'A-1' },
      { type: 'complete', account_id: 'bkd-1', backend_status: 'validating' },
    ];
    let captured: ReturnType<typeof useLoginSession> | null = null;
    const Child = defineComponent({
      setup() {
        captured = useLoginSession();
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: mockClient(events) });
    app.mount(document.createElement('div'));

    await captured!.start('bkd-1', 'cli_browser', {});
    expect(captured!.urlPrompt.value?.url).toBe('https://x');
    expect(captured!.urlPrompt.value?.user_code).toBe('A-1');
  });

  it('captures failed events', async () => {
    const events: LoginEvent[] = [
      { type: 'failed', code: 'cli_not_found', message: 'claude not installed' },
    ];
    let captured: ReturnType<typeof useLoginSession> | null = null;
    const Child = defineComponent({
      setup() {
        captured = useLoginSession();
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: mockClient(events) });
    app.mount(document.createElement('div'));

    await captured!.start('bkd-1', 'cli_browser', {});
    expect(captured!.status.value).toBe('failed');
    expect(captured!.errorCode.value).toBe('cli_not_found');
    expect(captured!.errorMessage.value).toBe('claude not installed');
  });

  it('streams stdout lines', async () => {
    const events: LoginEvent[] = [
      { type: 'stdout', text: 'line 1' },
      { type: 'stdout', text: 'line 2' },
      { type: 'complete', account_id: 'bkd-1', backend_status: 'validating' },
    ];
    let captured: ReturnType<typeof useLoginSession> | null = null;
    const Child = defineComponent({
      setup() {
        captured = useLoginSession();
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: mockClient(events) });
    app.mount(document.createElement('div'));

    await captured!.start('bkd-1', 'cli_browser', {});
    expect(captured!.stdoutLines.value).toEqual(['line 1', 'line 2']);
  });
});
