import { describe, it, expect, vi } from 'vitest';
import { createApp, defineComponent, h } from 'vue';
import { aiAccountsPlugin } from '../src/plugin';
import { useAiAccounts } from '../src/composables/useAiAccounts';
import { AiAccountsClient } from '@ai-accounts/ts-core';

const makeClient = () =>
  new AiAccountsClient({ baseUrl: 'http://t', fetch: vi.fn() });

describe('aiAccountsPlugin', () => {
  it('provides client to descendants', () => {
    let captured: unknown;
    const Child = defineComponent({
      setup() {
        const ctx = useAiAccounts();
        captured = ctx.client;
        return () => h('div');
      },
    });
    const app = createApp(Child);
    const client = makeClient();
    app.use(aiAccountsPlugin, { client });
    app.mount(document.createElement('div'));
    expect(captured).toBe(client);
  });

  it('routes events through onEvent handler', () => {
    const handler = vi.fn();
    const Child = defineComponent({
      setup() {
        const { emit } = useAiAccounts();
        emit({ type: 'wizard.opened', backendKind: 'claude' });
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: makeClient(), onEvent: handler });
    app.mount(document.createElement('div'));
    expect(handler).toHaveBeenCalledWith({ type: 'wizard.opened', backendKind: 'claude' });
  });

  it('catches handler errors as internal.handler_error', () => {
    const events: unknown[] = [];
    const handler = vi.fn().mockImplementation((e) => {
      events.push(e);
      if (e.type === 'wizard.opened') throw new Error('boom');
    });
    const Child = defineComponent({
      setup() {
        const { emit } = useAiAccounts();
        emit({ type: 'wizard.opened', backendKind: 'claude' });
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: makeClient(), onEvent: handler });
    app.mount(document.createElement('div'));
    expect(events).toHaveLength(2);
    expect((events[1] as { type: string }).type).toBe('internal.handler_error');
  });

  it('throws helpful error when used without plugin', () => {
    const Child = defineComponent({
      setup() {
        expect(() => useAiAccounts()).toThrow(/aiAccountsPlugin/);
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.mount(document.createElement('div'));
  });
});
