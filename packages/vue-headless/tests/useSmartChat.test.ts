import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useSmartChat } from '../src/composables/useSmartChat';

// Mutable events yielded by the mocked sendChat.
let mockEvents: any[] = [
  { kind: 'token', payload: 'Hello' },
  { kind: 'done', payload: { finish_reason: 'stop' } },
];
let mockStall = false;

// Mock useAiAccounts
vi.mock('../src/composables/useAiAccounts', () => ({
  useAiAccounts: () => ({
    client: {
      createChatSession: vi.fn().mockResolvedValue({ id: 'cht-1', backend_id: 'bkd-1', model: 'fake-1', title: null, created_at: '2026-04-13T00:00:00Z' }),
      getConversation: vi.fn().mockResolvedValue({ id: 'cht-1', messages: [] }),
      sendChat: vi.fn().mockImplementation(async function*(_req: unknown, opts?: { signal?: AbortSignal }) {
        if (mockStall) {
          await new Promise<void>((_, reject) => {
            const onAbort = () => reject(new DOMException('aborted', 'AbortError'));
            if (opts?.signal?.aborted) {
              onAbort();
              return;
            }
            opts?.signal?.addEventListener('abort', onAbort, { once: true });
          });
        }
        for (const ev of mockEvents) yield ev;
      }),
    },
    emit: vi.fn(),
  }),
}));

beforeEach(() => {
  mockEvents = [
    { kind: 'token', payload: 'Hello' },
    { kind: 'done', payload: { finish_reason: 'stop' } },
  ];
  mockStall = false;
});

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

  it('deduplicates events by _seq (skips <= lastSeq)', async () => {
    mockEvents = [
      { kind: 'token', payload: 'A', _seq: 1 },
      { kind: 'token', payload: 'B', _seq: 2 },
      // Replayed duplicates — should be skipped.
      { kind: 'token', payload: 'A', _seq: 1 },
      { kind: 'token', payload: 'B', _seq: 2 },
      { kind: 'token', payload: 'C', _seq: 3 },
      { kind: 'done', payload: { finish_reason: 'stop' }, _seq: 4 },
    ];
    const { createSession, send, messages } = useSmartChat();
    await createSession('bkd-1', 'fake-1');
    await send('Hi');
    // user + assistant; assistant should be 'ABC' (duplicates skipped).
    expect(messages.value[1].content).toBe('ABC');
  });

  it('triggers heartbeat stale error when no events arrive within timeout', async () => {
    vi.useFakeTimers();
    try {
      mockStall = true;
      const { createSession, send, error, isStreaming } = useSmartChat();
      await createSession('bkd-1', 'fake-1');
      const p = send('Hi');
      // Advance just past the 90s heartbeat window.
      await vi.advanceTimersByTimeAsync(91_000);
      expect(error.value).toMatch(/Connection lost/);
      expect(isStreaming.value).toBe(false);
      // The watchdog aborts the in-flight fetch — awaiting the pending promise
      // should resolve without raising, leaving the heartbeat message intact.
      await p;
      expect(error.value).toMatch(/Connection lost/);
    } finally {
      vi.useRealTimers();
    }
  });

  it('selects backend and resets account/model', () => {
    const { selectBackend, selectedBackend, selectedAccount, selectedModel } = useSmartChat();
    selectBackend('claude');
    expect(selectedBackend.value).toBe('claude');
    expect(selectedAccount.value).toBeNull();
    expect(selectedModel.value).toBeNull();
  });
});

describe('useSmartChat finalization', () => {
  it('exposes finalization state', () => {
    const chat = useSmartChat();
    expect(chat.canFinalize.value).toBe(false);
    expect(chat.isFinalizing.value).toBe(false);
    expect(chat.detectedConfig.value).toBeNull();
  });

  it('setConfigParser accepts a function', () => {
    const chat = useSmartChat();
    expect(() => chat.setConfigParser(() => null)).not.toThrow();
    expect(() => chat.setConfigParser(null)).not.toThrow();
  });
});
