/**
 * Append `prompt=…` + `login_hint=…` query params to an OAuth URL so the
 * IdP is forced to show its account picker / re-auth screen, even when
 * the user's default browser is already signed into a different account.
 *
 * Ported from Agented commit f52c55a — used by Antigravity (Google OAuth) and
 * Claude (Anthropic OAuth) login flows to support multi-account setups.
 *
 * @param url       Raw OAuth URL emitted by the backend CLI
 * @param email     Optional email — passed as `login_hint`
 * @param provider  'google' → prompt=select_account consent;
 *                  'claude' → prompt=login;
 *                  any other string → URL returned unchanged.
 */
export function forceFreshAccountPrompt(
  url: string,
  email: string,
  provider: 'google' | 'claude' | string,
): string {
  if (!url) return url;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    // Not a parseable URL — return as-is so the user still sees *something*.
    return url;
  }
  if (provider === 'google') {
    parsed.searchParams.set('prompt', 'select_account consent');
  } else if (provider === 'claude') {
    parsed.searchParams.set('prompt', 'login');
  } else {
    return url;
  }
  if (email) parsed.searchParams.set('login_hint', email);
  return parsed.toString();
}
