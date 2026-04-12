import { describe, it, expect, vi } from 'vitest';
import { useConversation } from '../src/composables/useConversation';

function mockClient() {
  return {
    createConversation: vi.fn().mockResolvedValue({
      id: 'cht-1', backend_id: 'bkd-1', model: 'fake-1', title: null, created_at: '2026-04-12T00:00:00Z',
    }),
    getConversation: vi.fn().mockResolvedValue({
      id: 'cht-1', backend_id: 'bkd-1', model: 'fake-1', title: null, created_at: '2026-04-12T00:00:00Z',
      messages: [{ id: 'msg-1', role: 'user', content: 'Hi', created_at: '2026-04-12T00:00:00Z', model: null, tokens_in: null, tokens_out: null }],
    }),
    streamChat: vi.fn().mockImplementation(async function*() {
      yield { kind: 'token', text: 'Hello', finish_reason: null, model: null, tokens_in: null, tokens_out: null };
      yield { kind: 'done', text: null, finish_reason: 'stop', model: 'fake-1', tokens_in: 5, tokens_out: 1 };
    }),
  } as any;
}

describe('useConversation', () => {
  it('creates a session', async () => {
    const { create, sessionId } = useConversation(mockClient());
    await create('bkd-1', 'fake-1');
    expect(sessionId.value).toBe('cht-1');
  });
  it('loads a session with messages', async () => {
    const { load, messages } = useConversation(mockClient());
    await load('cht-1');
    expect(messages.value).toHaveLength(1);
  });
  it('sends a message and streams response', async () => {
    const client = mockClient();
    const { create, send, messages } = useConversation(client);
    await create('bkd-1', 'fake-1');
    await send('Hi');
    expect(messages.value).toHaveLength(2);
    expect(messages.value[1].content).toBe('Hello');
  });
});
