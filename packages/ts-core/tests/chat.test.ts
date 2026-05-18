import { describe, it, expect } from 'vitest';
import type { ChatDelta, ChatSessionDTO } from '../src/types/chat';

describe('ChatDelta types', () => {
  it('token delta has expected shape', () => {
    const delta: ChatDelta = { kind: 'token', payload: 'Hello', finish_reason: null, model: null, tokens_in: null, tokens_out: null };
    expect(delta.kind).toBe('token');
    expect(delta.payload).toBe('Hello');
  });
  it('done delta has usage info', () => {
    const delta: ChatDelta = { kind: 'done', payload: null, finish_reason: 'stop', model: 'claude-sonnet-4-20250514', tokens_in: 50, tokens_out: 10 };
    expect(delta.finish_reason).toBe('stop');
  });
});

describe('ChatSessionDTO', () => {
  it('has expected shape', () => {
    const s: ChatSessionDTO = { id: 'cht-abc', backend_id: 'bkd-123', model: 'claude-sonnet-4-20250514', title: null, created_at: '2026-04-12T00:00:00Z' };
    expect(s.id).toBe('cht-abc');
  });
});
