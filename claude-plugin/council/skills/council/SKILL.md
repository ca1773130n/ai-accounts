---
name: council
description: Use when the user says "council it", "convene the council", "let the council decide", or asks to delegate a pending decision (e.g. an AskUserQuestion choice, an architecture fork, a naming/library/approach choice) to a council of their AI accounts. Convenes a debate via the ai-accounts sidecar's council API through the `aia-council` CLI and adopts the verdict.
---

# Council — delegate a decision to a panel of your AI accounts

The user's ai-accounts server can convene a **decision council**: five
role-lensed members (pragmatist, architect, risk-analyst, user-advocate,
contrarian) backed by the user's READY AI accounts (roles are distributed
round-robin; a single account backs all roles), who take positions, debate
anonymized rebuttals, vote, and let a chairman issue a final decision.

## When this triggers

- The user answers a pending question (yours or theirs) with "council it" or
  similar — the decision you were about to ask them is the council's input.
- The user asks to have "the council" settle any fork in the road.

## Procedure

1. **Assemble the decision packet.**
   - *Question*: one clear sentence. If an AskUserQuestion was pending, use it.
   - *Options*: 2–4 candidates, each as `"<label> — <one-line description>"`.
     Use the pending question's options verbatim (label + description) when
     they exist; otherwise enumerate the alternatives under discussion.
   - *Context brief*: write to a temp file. ≤300 words covering: what is being
     built, hard constraints (deadlines, stack, compatibility), what has been
     tried or ruled out and why, and any facts a debater would need. Include
     relevant `file:line` references. Never include secrets/tokens.

2. **Run the council.**

   ```bash
   aia-council \
     -q "<question>" \
     -o "<option 1>" -o "<option 2>" [...] \
     --context-file /tmp/council-brief.md \
     --json
   ```

   - `aia-council` ships with `npm install -g @ai-accounts/council` (zero-dep
     Node) or `pip install ai-accounts-core` (>= 0.4.5) — identical contract.
   - It needs a running ai-accounts server (default `http://127.0.0.1:30000`;
     override with `AIA_URL`, bearer key via `AI_ACCOUNTS_API_KEY`).
   - Progress streams to stderr; stdout is the decision JSON. A run takes
     roughly 1–3 minutes (two debate stages plus a chairman pass) — **run the
     Bash call with a 10-minute timeout** (the default 2-minute Bash timeout
     will kill a real deliberation mid-flight and waste account quota).

3. **Adopt the verdict.** Parse stdout JSON:

   ```json
   {
     "choice": 2,
     "choice_label": "...",
     "confidence": 0.8,
     "rationale": "...",
     "dissent": "...",
     "tally": {"...": 3},
     "decided_by": "chairman" | "majority_fallback"
   }
   ```

   Report to the user in 3–5 sentences: the chosen option, the council's
   rationale, the strongest dissent, and the vote tally. Then **proceed with
   the chosen option** — the user delegated this decision; do not re-ask
   unless the council errored.

## Failure handling

- Exit code 1 with "cannot reach" → the ai-accounts server isn't running.
  Tell the user (e.g. `pnpm start` in the ai-accounts playground, or their
  host app) and fall back to asking them the original question directly.
- `council_error: no READY accounts…` → the user has no usable accounts;
  fall back to asking them.
- Never silently substitute your own choice for a failed council run — say
  what happened.
