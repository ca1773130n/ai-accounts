import { describe, it, expect } from 'vitest';
import type { AccountHealthDTO, PickResultDTO, FallbackChainEntryDTO } from '../src/types/scheduler';

describe('Scheduler types', () => {
  it('AccountHealthDTO shape', () => {
    const h: AccountHealthDTO = {
      backend_id: 'bkd-1', kind: 'claude', windows: [{ window_type: 'five_hour', usage_percent: 42, resets_at: null, tokens_used: null, tokens_limit: null }],
      rate_limited_until: null, rate_limit_reason: null, last_used_at: null, last_polled_at: null,
    };
    expect(h.windows[0].usage_percent).toBe(42);
  });
  it('PickResultDTO shape', () => {
    const p: PickResultDTO = { backend_id: 'bkd-1', kind: 'claude', isolation_dir: '/tmp/x', retry_after: null };
    expect(p.kind).toBe('claude');
  });
  it('FallbackChainEntryDTO shape', () => {
    const e: FallbackChainEntryDTO = { backend_id: 'bkd-1', priority: 0 };
    expect(e.priority).toBe(0);
  });
});
