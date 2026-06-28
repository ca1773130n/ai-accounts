import { describe, it, expect } from 'vitest';
import type {
  SmartChatEvent,
  BackendResponse,
  SynthesisState,
  BackendOption,
  ChatMode,
  SendChatRequest,
} from '../src/types/smart-chat';

describe('SmartChatEvent variants', () => {
  it('token event has kind and payload', () => {
    const e: SmartChatEvent = { kind: 'token', payload: 'hello' };
    expect(e.kind).toBe('token');
  });

  it('done event has record payload', () => {
    const e: SmartChatEvent = { kind: 'done', payload: { usage: 42 } };
    expect(e.kind).toBe('done');
  });

  it('error event has string payload', () => {
    const e: SmartChatEvent = { kind: 'error', payload: 'something failed' };
    expect(e.kind).toBe('error');
  });

  it('backend_delta carries backend and text', () => {
    const e: SmartChatEvent = { kind: 'backend_delta', backend: 'claude', text: 'hi' };
    expect(e.kind).toBe('backend_delta');
    if (e.kind === 'backend_delta') {
      expect(e.backend).toBe('claude');
      expect(e.text).toBe('hi');
    }
  });

  it('backend_complete carries backend', () => {
    const e: SmartChatEvent = { kind: 'backend_complete', backend: 'gpt' };
    expect(e.kind).toBe('backend_complete');
  });

  it('backend_error carries backend and error', () => {
    const e: SmartChatEvent = { kind: 'backend_error', backend: 'gpt', error: 'rate limited' };
    if (e.kind === 'backend_error') {
      expect(e.error).toBe('rate limited');
    }
  });

  it('backend_timeout carries backend', () => {
    const e: SmartChatEvent = { kind: 'backend_timeout', backend: 'antigravity' };
    expect(e.kind).toBe('backend_timeout');
  });

  it('synthesis_start carries primary_backend and backends_collected', () => {
    const e: SmartChatEvent = {
      kind: 'synthesis_start',
      primary_backend: 'claude',
      backends_collected: ['claude', 'gpt'],
    };
    if (e.kind === 'synthesis_start') {
      expect(e.primary_backend).toBe('claude');
      expect(e.backends_collected).toEqual(['claude', 'gpt']);
    }
  });

  it('synthesis_delta carries text', () => {
    const e: SmartChatEvent = { kind: 'synthesis_delta', text: 'synthesized' };
    if (e.kind === 'synthesis_delta') {
      expect(e.text).toBe('synthesized');
    }
  });

  it('synthesis_complete has no extra fields', () => {
    const e: SmartChatEvent = { kind: 'synthesis_complete' };
    expect(e.kind).toBe('synthesis_complete');
  });

  it('synthesis_error carries error', () => {
    const e: SmartChatEvent = { kind: 'synthesis_error', error: 'failed' };
    if (e.kind === 'synthesis_error') {
      expect(e.error).toBe('failed');
    }
  });
});

describe('BackendResponse', () => {
  it('has required fields', () => {
    const r: BackendResponse = {
      backend: 'claude',
      content: 'Hello',
      status: 'complete',
    };
    expect(r.backend).toBe('claude');
    expect(r.status).toBe('complete');
  });

  it('accepts optional error', () => {
    const r: BackendResponse = {
      backend: 'gpt',
      content: '',
      status: 'error',
      error: 'timeout',
    };
    expect(r.error).toBe('timeout');
  });
});

describe('SynthesisState', () => {
  it('has required fields', () => {
    const s: SynthesisState = {
      status: 'streaming',
      content: 'partial',
      primaryBackend: 'claude',
      backendsCollected: ['claude', 'gpt'],
    };
    expect(s.status).toBe('streaming');
    expect(s.backendsCollected).toHaveLength(2);
  });

  it('accepts optional error', () => {
    const s: SynthesisState = {
      status: 'error',
      content: '',
      primaryBackend: 'claude',
      backendsCollected: [],
      error: 'synthesis failed',
    };
    expect(s.error).toBe('synthesis failed');
  });
});

describe('BackendOption', () => {
  it('has required fields', () => {
    const o: BackendOption = {
      kind: 'claude',
      displayName: 'Claude',
      accounts: ['acc-1'],
      models: ['opus', 'sonnet'],
    };
    expect(o.kind).toBe('claude');
    expect(o.models).toHaveLength(2);
  });
});

describe('ChatMode', () => {
  it('is a union of three strings', () => {
    const a: ChatMode = 'single';
    const b: ChatMode = 'all';
    const c: ChatMode = 'compound';
    expect([a, b, c]).toEqual(['single', 'all', 'compound']);
  });
});

describe('SendChatRequest', () => {
  it('has required fields', () => {
    const req: SendChatRequest = {
      session_id: 'sess-1',
      content: 'Hello',
    };
    expect(req.session_id).toBe('sess-1');
  });

  it('accepts optional fields', () => {
    const req: SendChatRequest = {
      session_id: 'sess-1',
      content: 'Hello',
      mode: 'compound',
      backend_kind: 'claude',
      account_id: 'acc-1',
      model: 'opus',
    };
    expect(req.mode).toBe('compound');
    expect(req.backend_kind).toBe('claude');
  });
});
