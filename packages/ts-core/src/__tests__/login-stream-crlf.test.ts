import { describe, it, expect } from 'vitest'
import { parseSseLoginEvents } from '../client/login-stream'

/**
 * Regression for the CRLF-vs-LF parser bug fixed in 0.3.5.
 *
 * Litestar's ServerSentEvent emits frames separated by `\r\n\r\n` (CRLF).
 * The parser previously searched only for `\n\n` and silently yielded
 * nothing, causing the login wizard to hang on "Starting login session...".
 */

function mockResponse(body: string): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(body))
      controller.close()
    },
  })
  return new Response(stream, { headers: { 'content-type': 'text/event-stream' } })
}

describe('parseSseLoginEvents — frame-separator normalization', () => {
  it('parses frames separated by CRLF (Litestar default)', async () => {
    const body =
      'event: login\r\n' +
      'data: {"type":"progress","label":"Starting","percent":null}\r\n\r\n' +
      'event: login\r\n' +
      'data: {"type":"stdout","text":"hello"}\r\n\r\n' +
      'event: login\r\n' +
      'data: {"type":"url_prompt","prompt_id":"auth","url":"https://claude.com/cai/oauth/authorize?code=true"}\r\n\r\n'

    const events: unknown[] = []
    for await (const ev of parseSseLoginEvents(mockResponse(body))) {
      events.push(ev)
    }

    expect(events).toHaveLength(3)
    expect((events[0] as { type: string }).type).toBe('progress')
    expect((events[1] as { type: string }).type).toBe('stdout')
    expect((events[2] as { type: string; url: string }).type).toBe('url_prompt')
    expect((events[2] as { url: string }).url).toContain('https://claude.com/cai/oauth/')
  })

  it('still parses frames separated by LF (non-Litestar SSE emitters)', async () => {
    const body =
      'event: login\n' +
      'data: {"type":"progress","label":"x","percent":null}\n\n' +
      'event: login\n' +
      'data: {"type":"stdout","text":"y"}\n\n'

    const events: unknown[] = []
    for await (const ev of parseSseLoginEvents(mockResponse(body))) {
      events.push(ev)
    }
    expect(events).toHaveLength(2)
  })
})
