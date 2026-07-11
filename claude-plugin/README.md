# ai-accounts Claude Code plugins

## council

Say **"council it"** on any pending decision in a Claude Code session and a
council of your AI accounts — convened through your running ai-accounts
server — debates the options (positions → anonymized rebuttals → votes →
chairman verdict) and hands the decision back. One account? Five role-agents
debate on it. Several accounts? The roles spread across them.

### Install

```bash
# inside Claude Code
/plugin marketplace add ca1773130n/ai-accounts
/plugin install council@ai-accounts
```

Or copy the skill directly:

```bash
cp -r claude-plugin/council/skills/council ~/.claude/skills/
```

### Requirements

- The `aia-council` CLI — either `npm install -g @ai-accounts/council`
  (zero-dependency Node) or `pip install ai-accounts-core` (>= 0.4.5);
  both provide the identical command.
- A running ai-accounts server with at least one READY account
  (`AIA_URL` overrides the default `http://127.0.0.1:30000`;
  `AI_ACCOUNTS_API_KEY` if the server uses ApiKeyAuth).

### Use

When Claude asks you to choose a direction (or any fork comes up), reply:

> council it

Claude packages the question, the options, and a context brief, runs
`aia-council`, and proceeds with the council's verdict — reporting the
rationale, the strongest dissent, and the vote tally.
