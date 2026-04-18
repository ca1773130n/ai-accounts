import { describe, it, expect } from 'vitest';
import { forceFreshAccountPrompt } from '../src/components/forceFreshAccountPrompt';

describe('forceFreshAccountPrompt', () => {
  it('appends prompt=select_account consent + login_hint for google', () => {
    const out = forceFreshAccountPrompt(
      'https://accounts.google.com/o/oauth2/v2/auth?client_id=abc&scope=openid',
      'alice@example.com',
      'google',
    );
    const u = new URL(out);
    expect(u.searchParams.get('prompt')).toBe('select_account consent');
    expect(u.searchParams.get('login_hint')).toBe('alice@example.com');
    expect(u.searchParams.get('client_id')).toBe('abc');
  });

  it('appends prompt=login + login_hint for claude', () => {
    const out = forceFreshAccountPrompt(
      'https://claude.ai/oauth/authorize?state=xyz',
      'bob@example.com',
      'claude',
    );
    const u = new URL(out);
    expect(u.searchParams.get('prompt')).toBe('login');
    expect(u.searchParams.get('login_hint')).toBe('bob@example.com');
    expect(u.searchParams.get('state')).toBe('xyz');
  });

  it('omits login_hint when email is empty', () => {
    const out = forceFreshAccountPrompt(
      'https://accounts.google.com/o/oauth2/v2/auth',
      '',
      'google',
    );
    const u = new URL(out);
    expect(u.searchParams.has('login_hint')).toBe(false);
    expect(u.searchParams.get('prompt')).toBe('select_account consent');
  });

  it('overwrites a pre-existing prompt param', () => {
    const out = forceFreshAccountPrompt(
      'https://accounts.google.com/o/oauth2/v2/auth?prompt=none',
      '',
      'google',
    );
    expect(new URL(out).searchParams.get('prompt')).toBe('select_account consent');
  });

  it('returns the URL unchanged for unknown providers', () => {
    const raw = 'https://example.com/auth?x=1';
    expect(forceFreshAccountPrompt(raw, 'eve@example.com', 'unknown')).toBe(raw);
  });

  it('returns the input unchanged when URL is unparseable', () => {
    expect(forceFreshAccountPrompt('not a url', 'a@b.c', 'google')).toBe('not a url');
  });

  it('returns empty string when url is empty', () => {
    expect(forceFreshAccountPrompt('', 'a@b.c', 'google')).toBe('');
  });
});
