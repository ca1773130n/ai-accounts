import type { LoginEvent, LoginFailed } from '../types/login';

export async function* parseSseLoginEvents(
  response: Response
): AsyncIterable<LoginEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let consecutiveParseErrors = 0;

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      // Normalize CRLF -> LF. Litestar's ServerSentEvent emits frames
      // separated by `\r\n\r\n` (SSE spec allows both CRLF and LF forms),
      // but the frame split below looks for `\n\n`. Without this
      // normalization the parser yields nothing and the login wizard hangs
      // on "Starting login session...".
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');

      while (true) {
        const sep = buffer.indexOf('\n\n');
        if (sep === -1) break;
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);

        const dataLine = frame.split('\n').find((l) => l.startsWith('data: '));
        if (!dataLine) continue;
        const payload = dataLine.slice(6);
        try {
          const parsed = JSON.parse(payload);
          // Basic shape validation — event must have a 'type' field
          if (parsed && typeof parsed === 'object' && typeof parsed.type === 'string') {
            consecutiveParseErrors = 0;
            yield parsed as LoginEvent;
          } else {
            console.warn('[ai-accounts] SSE frame missing type field:', payload.slice(0, 200));
            consecutiveParseErrors++;
          }
        } catch {
          console.warn('[ai-accounts] malformed SSE frame:', payload.slice(0, 200));
          consecutiveParseErrors++;
        }
        if (consecutiveParseErrors >= 3) {
          yield {
            type: 'failed',
            code: 'stream_corrupt',
            message: 'Multiple malformed SSE frames received',
          } as LoginFailed;
          return;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
