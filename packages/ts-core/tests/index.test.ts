import { describe, it, expect } from 'vitest';
import { version, WIRE_PROTOCOL_VERSION } from '../src/index';

describe('ts-core', () => {
  it('exposes a version string', () => {
    expect(typeof version).toBe('string');
  });

  it('re-exports WIRE_PROTOCOL_VERSION', () => {
    expect(WIRE_PROTOCOL_VERSION).toBe(1);
  });
});
