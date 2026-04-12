import type { SmartChatEvent } from '../types/smart-chat';

export async function* parseSseSmartChatEvents(response: Response): AsyncGenerator<SmartChatEvent> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop() ?? '';
    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (line.startsWith('data: ')) {
          try {
            yield JSON.parse(line.slice(6).trim()) as SmartChatEvent;
          } catch {
            console.warn('[ai-accounts] malformed smart chat SSE frame');
          }
        }
      }
    }
  }
}
