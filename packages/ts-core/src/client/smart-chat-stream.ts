import type { SmartChatEvent } from '../types/smart-chat';
import { parseSseFrames } from './sse-parser';

export async function* parseSseSmartChatEvents(response: Response): AsyncGenerator<SmartChatEvent> {
  for await (const payload of parseSseFrames(response)) {
    const trimmed = payload.trim();
    if (!trimmed) continue;
    try {
      yield JSON.parse(trimmed) as SmartChatEvent;
    } catch {
      console.warn('[ai-accounts] malformed smart chat SSE frame dropped:', trimmed.slice(0, 200));
    }
  }
}
