import type { ChatDelta } from '../types/chat';
import { parseSseFrames } from './sse-parser';

export async function* parseSseChatEvents(response: Response): AsyncGenerator<ChatDelta> {
  for await (const payload of parseSseFrames(response)) {
    const trimmed = payload.trim();
    if (!trimmed) continue;
    try {
      yield JSON.parse(trimmed) as ChatDelta;
    } catch {
      console.warn('[ai-accounts] malformed SSE chat frame dropped:', trimmed.slice(0, 200));
    }
  }
}
