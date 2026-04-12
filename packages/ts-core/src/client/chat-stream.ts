import type { ChatDelta } from '../types/chat';

export async function* parseSseChatEvents(response: Response): AsyncGenerator<ChatDelta> {
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
          const payload = line.slice(6).trim();
          if (!payload) continue;
          try {
            yield JSON.parse(payload) as ChatDelta;
          } catch {
            console.warn('[ai-accounts] malformed SSE chat frame dropped:', payload.slice(0, 200));
          }
        }
      }
    }
  }
}
