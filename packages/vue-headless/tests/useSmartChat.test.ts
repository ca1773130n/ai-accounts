import { describe, it, expect, vi } from 'vitest';
import { useSmartChat } from '../src/composables/useSmartChat';

// Mock useAiAccounts
vi.mock('../src/composables/useAiAccounts', () => ({
  useAiAccounts: () => ({
    client: {
      createChatSession: vi.fn().mockResolvedValue({ id: 'cht-1', backend_id: 'bkd-1', model: 'fake-1', title: null, created_at: '2026-04-13T00:00:00Z' }),
      getConversation: vi.fn().mockResolvedValue({ id: 'cht-1', messages: [] }),
      sendChat: vi.fn().mockImplementation(async function*() {
        yield { kind: 'token', payload: 'Hello' };
        yield { kind: 'done', payload: { finish_reason: 'stop' } };
      }),
    },
    emit: vi.fn(),
  }),
}));

describe('useSmartChat', () => {
  it('creates a session', async () => {
    const { createSession, sessionId } = useSmartChat();
    await createSession('bkd-1', 'fake-1');
    expect(sessionId.value).toBe('cht-1');
  });

  it('sends and streams single mode', async () => {
    const { createSession, send, messages } = useSmartChat();
    await createSession('bkd-1', 'fake-1');
    await send('Hi');
    expect(messages.value.length).toBe(2); // user + assistant
    expect(messages.value[1].content).toBe('Hello');
  });

  it('sets mode', () => {
    const { setMode, chatMode } = useSmartChat();
    setMode('all');
    expect(chatMode.value).toBe('all');
  });

  it('selects backend and resets account/model', () => {
    const { selectBackend, selectedBackend, selectedAccount, selectedModel } = useSmartChat();
    selectBackend('claude');
    expect(selectedBackend.value).toBe('claude');
    expect(selectedAccount.value).toBeNull();
    expect(selectedModel.value).toBeNull();
  });
});
