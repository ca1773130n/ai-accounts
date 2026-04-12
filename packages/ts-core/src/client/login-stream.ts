import type { LoginEvent } from '../types/login';

export async function* parseSseLoginEvents(
  response: Response
): AsyncIterable<LoginEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      while (true) {
        const sep = buffer.indexOf('\n\n');
        if (sep === -1) break;
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);

        const dataLine = frame.split('\n').find((l) => l.startsWith('data: '));
        if (!dataLine) continue;
        const payload = dataLine.slice(6);
        try {
          yield JSON.parse(payload) as LoginEvent;
        } catch {
          // malformed frame — skip
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
