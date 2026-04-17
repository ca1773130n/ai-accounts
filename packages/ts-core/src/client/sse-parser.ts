/**
 * SSE frame parser that handles CRLF/LF endings, multi-line `data:` fields,
 * and flushes the decoder + residual buffer on EOF so the last event isn't
 * dropped when the server closes without a trailing blank line.
 *
 * Yields the raw payload string of each event's joined `data:` lines.
 * Callers are responsible for JSON-parsing and shape-validating the payload.
 */
export async function* parseSseFrames(response: Response): AsyncGenerator<string> {
  if (!response.body) {
    throw new Error('[ai-accounts] SSE response has no body');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  function* drain(flush: boolean): Generator<string> {
    while (true) {
      const boundary = findBoundary(buf);
      if (boundary === null) {
        if (!flush) return;
        if (!buf.trim()) return;
        const tail = buf;
        buf = '';
        const payload = extractDataPayload(tail);
        if (payload !== null) yield payload;
        return;
      }
      const frame = buf.slice(0, boundary.index);
      buf = buf.slice(boundary.index + boundary.length);
      const payload = extractDataPayload(frame);
      if (payload !== null) yield payload;
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        buf += decoder.decode();
        yield* drain(true);
        return;
      }
      buf += decoder.decode(value, { stream: true });
      yield* drain(false);
    }
  } finally {
    try { reader.releaseLock(); } catch { /* already released */ }
  }
}

/**
 * Find the first event boundary (blank line with CRLF or LF endings).
 * Returns the start index and the length of the boundary so the caller can
 * slice the frame and advance past the separator. Returns null if none found.
 */
function findBoundary(buf: string): { index: number; length: number } | null {
  let best: { index: number; length: number } | null = null;
  const candidates = ['\r\n\r\n', '\n\n', '\r\r'];
  for (const sep of candidates) {
    const i = buf.indexOf(sep);
    if (i === -1) continue;
    if (!best || i < best.index) best = { index: i, length: sep.length };
  }
  return best;
}

function extractDataPayload(frame: string): string | null {
  // Per the EventSource spec, multiple `data:` lines in a single event are
  // joined with `\n`. Comment lines (starting with `:`) and other fields
  // (event:, id:, retry:) are ignored here — callers needing those should
  // extend this parser.
  const dataLines: string[] = [];
  for (const rawLine of frame.split(/\r?\n/)) {
    if (!rawLine.startsWith('data:')) continue;
    const rest = rawLine.slice(5);
    // SSE allows `data: foo` and `data:foo` — strip one leading space if present.
    dataLines.push(rest.startsWith(' ') ? rest.slice(1) : rest);
  }
  if (dataLines.length === 0) return null;
  return dataLines.join('\n');
}
