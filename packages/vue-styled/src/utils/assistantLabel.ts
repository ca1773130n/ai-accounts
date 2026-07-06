/**
 * Display-name helpers for the answering AI backend + model.
 *
 * Chat bubbles label the assistant by *who actually answered* — the
 * backend (Claude / Codex / Antigravity / OpenCode) plus, when known, the
 * model — instead of a generic "AI". These helpers turn the raw
 * backend kind / model id stored on a message into human labels.
 */

const BACKEND_DISPLAY_NAMES: Record<string, string> = {
  claude: 'Claude',
  claude_custom: 'Claude (self-hosted)',
  codex: 'Codex',
  antigravity: 'Antigravity',
  opencode: 'OpenCode',
  deepseek: 'DeepSeek',
  goose: 'Goose',
  aider: 'Aider',
  crush: 'Crush',
  openai_compat: 'OpenAI-compatible',
  openrouter: 'OpenRouter',
  kimi: 'Kimi',
};

/**
 * Human label for a backend kind. Returns '' for a missing kind or the
 * placeholder `'auto'` (no concrete backend resolved yet) so callers can
 * fall back to a generic name.
 */
export function backendDisplayName(backend?: string | null): string {
  if (!backend || backend === 'auto') return '';
  return (
    BACKEND_DISPLAY_NAMES[backend] ??
    backend.charAt(0).toUpperCase() + backend.slice(1)
  );
}

const MODEL_DISPLAY_NAMES: Record<string, string> = {
  opus: 'Opus',
  sonnet: 'Sonnet',
  haiku: 'Haiku',
  codex: 'Codex',
  zen: 'Zen',
};

/**
 * Human label for a model id. Known short ids are capitalized; anything
 * else (full model strings like `gpt-5.1` or `claude-opus-4-8`) passes
 * through unchanged. Returns '' for a missing model so the pill can be
 * hidden.
 */
export function modelDisplayName(model?: string | null): string {
  if (!model) return '';
  return MODEL_DISPLAY_NAMES[model] ?? model;
}
