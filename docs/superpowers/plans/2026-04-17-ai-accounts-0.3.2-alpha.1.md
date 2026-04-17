# ai-accounts 0.3.2-alpha.1 — Agented parity

**Branch**: `feat/0.3.2-agented-parity` · **Shipped**: 2026-04-17 · **Tag**:
tagged after release commit `2a747f7`.

## Intent

Bring `ai-accounts` to parity with Agented's three in-flight OAuth fixes
(Agented commits `14d0b23` and `78d270c`) so Agented can un-pin from its
local-path workarounds and consume `ai-accounts` via its pinned release
version again. All three fixes target real bugs hit during Claude Code
account registration on remote machines.

## What landed

### 1. Claude v2 auth: `--claudeai` flag + email pre-fill (commit `48af9f6`)

Previously `ClaudeBackend.begin_login("cli_browser")` always used the v1
interactive `claude` + `/login` slash-command path, which binds the OAuth
callback server to `localhost` on the machine running the CLI. On remote
boxes (SSH, containers) the callback can't be reached from the user's
browser. The v1 workaround involved manual paste-back URLs, which our
cliproxy forwarder doesn't handle.

**Fix:** when `config["email"]` is provided, use
`claude auth login --claudeai --email <email>`. v2 uses
`platform.claude.com/oauth/code/callback` as the redirect — a public
endpoint — so it works anywhere without a local bind. `--email`
pre-fills Google's account picker to prevent wrong-account mistakes.
`ClaudeBackend.metadata` now advertises `email` as an optional input on
the `cli_browser` flow so the wizard can prompt for it. The v1 path
remains the fallback when no email is configured.

Also bundled with this commit:
- **IPv6 callback**: `forward_cliproxy_callback` tries `[::1]`, then
  `127.0.0.1`, then `localhost`. Claude CLI v2.1.92+ binds to the IPv6
  loopback on macOS; cliproxy still listens on IPv4.
- **URL capture hardening**: `_URL_IN_OUTPUT_RE` now matches
  `platform.claude.com` alongside `claude.ai` / `console.anthropic.com`.
- Regression tests: `tests/cliproxy/test_manager_ipv6.py` pins the
  IPv6-first order, fallback behavior, aggregated error shape, and
  last-status surfacing.

### 2. Gemini OAuth: `client_secret` + peek-don't-pop PKCE state (commit `a0c75b2`)

Agented's `main` had two separate bugs fixed as a pair:

a. **Missing `client_secret`**: Google's token-exchange endpoint for the
   web-client credential type requires a `client_secret` field alongside
   `client_id`. Without it the exchange fails with
   `"client_secret is missing"`. The secret is publicly embedded in the
   Gemini CLI itself (constant `GOCSPX-...`), so it's a configuration
   constant — not a real secret, but required by the protocol.

b. **State wiped on first transient failure**: the Agented Flask handler
   popped the PKCE `code_verifier` / `state` from its shared dict
   *before* attempting the token exchange. Any transient failure
   (network blip, Google 5xx, typo in the auth code) destroyed the PKCE
   material and forced a hard re-login.

**Fix:** `_exchange_code()` now includes `client_secret`, and
`_GeminiDirectOAuthSession.events()` retries up to 3 times on exchange
failure while keeping the PKCE state intact — peek-don't-pop semantics.
Since this codebase uses a session-object model (not a global dict),
the port is in-session retry rather than peek/pop on a shared map, but
the user-visible behavior matches Agented.

Regression tests:
- `test_token_exchange_posts_client_secret` — POST body includes the
  `GOCSPX-…` key.
- `test_pkce_state_survives_transient_failure` — same `code_verifier`
  reused across two exchange attempts; second succeeds.
- `test_post_success_state_not_retrievable` — `session.done` flips to
  True after success; further `respond()` calls no-op.
- `test_direct_oauth_reports_token_exchange_failure` — updated to submit
  3 bad codes (exhausts the new retry budget).

### 3. Codex OAuth URL detection (commit `a9825db`)

`_CODEX_URL_RE` previously only matched `chatgpt.com/auth/*`. Codex CLI's
`login` command emits `https://auth.openai.com/*` during the device-code
flow. Broadening the regex lets the interactive-login state machine emit
`UrlPrompt` immediately when either host appears, enabling auto-open in
the frontend. Regression test in `tests/backends/test_codex_oauth_url.py`.

### 4. Post-release audit sweep (commits `969e9e0`, `6c7db3f`)

Not part of the Agented parity goal, but landed on the same branch to
keep the release cycle clean:

- Ported `PR_SET_PDEATHSIG` (RISKS H-5) and rmtree logging (SILENT H-4)
  forward from the abandoned `feat/0.3.0-alpha.2-4` branch.
- L-2 fix: `_ACTIVE_PROCS` now keyed on `uuid4().hex` instead of
  `id(proc)`.
- Additional temp-dir cleanup on all exit paths of
  `start_cliproxy_login` (`CliproxyLoginInfo.fake_dir` field + reaper
  cleanup).
- Re-verified every item in `RISKS-AND-BUGS.md` and `SILENT-FAILURES.md`
  against main; 13 RISKS items now closed (up from 11 at 0.3.1);
  `SILENT-FAILURES.md` gained one reclassification (H-07 →
  accepted design) and three confirmed-open items with specific
  file:line refs (H-02, H-03, M-13).
- Refreshed `MAINTENANCE.md` to 0.3.1 / 0.3.2-alpha.1 reality, removed
  the obsolete "chat()/pty() raise NotImplementedError" tech-debt
  entries, added operator-facing sections for the auth middleware (5.6)
  and schema migrations (5.7).

## Release checklist

- [x] **Step 1**: Update `CHANGELOG.md` with a 0.3.2-alpha.1 entry.
- [x] **Step 2**: Bump all 5 package versions to 0.3.2-alpha.1 (Python:
  `0.3.2a1`; npm: `0.3.2-alpha.1`).
- [x] **Step 3**: Regenerate `uv.lock`.
- [x] **Step 4**: Run full test suite — 373 Python + 187 JS = 560.
- [x] **Step 5**: Commit `release: 0.3.2-alpha.1 — Agented parity`
  (`2a747f7`).
- [ ] **Step 6**: Rebuild and publish npm packages (`pnpm -r build` +
  `pnpm publish -r --access public --no-git-checks`).
- [ ] **Step 7**: Build and publish Python wheels
  (`uv build --package ai-accounts-core --out-dir dist/0.3.2-alpha.1` +
  `uv publish dist/0.3.2-alpha.1/*`).
- [ ] **Step 8**: Tag `v0.3.2-alpha.1`.
- [ ] **Step 9**: Push branch + tag.
- [ ] **Step 10**: Bump Agented's pins from `0.3.1` → `0.3.2a1` and
  verify.

## Known deferred

Tracked in `RISKS-AND-BUGS.md` for post-0.3.2:

- **C-5 (Gemini plaintext OAuth tokens)**: architectural tradeoff
  (CLI-mandated on-disk format). Moves to 0.4.0 when the credential
  model can carry a vault-encrypted shadow copy.
- **M-1 (API key plain HTTP body)**: mitigation-only (TLS termination
  at the reverse proxy); no code change planned.
