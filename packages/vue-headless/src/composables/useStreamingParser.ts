export interface UseStreamingParserOptions {
  onFlush?: () => void
  /** Max buffered chars before pre-init writes are dropped (prevents leak when smd fails to resolve). */
  maxPendingChars?: number
}

export interface UseStreamingParserReturn {
  init: (container: HTMLElement) => void
  write: (text: string) => void
  finalize: () => void
  destroy: () => void
}

type SmdModule = {
  default_renderer: (el: HTMLElement) => unknown
  parser: (renderer: unknown) => unknown
  parser_write: (parser: unknown, text: string) => void
  parser_end: (parser: unknown) => void
}

const DEFAULT_MAX_PENDING = 1_000_000

let smdResolutionWarned = false

async function resolveSmd(): Promise<SmdModule | null> {
  const injected = (globalThis as Record<string, unknown>).__smd
  if (injected) return injected as SmdModule
  try {
    // streaming-markdown is an optional peer dep; may not be installed or typed.
    const mod = (await import(/* @vite-ignore */ 'streaming-markdown' as string)) as unknown
    return mod as SmdModule
  } catch (err) {
    if (!smdResolutionWarned) {
      smdResolutionWarned = true
      // eslint-disable-next-line no-console
      console.warn(
        '[useStreamingParser] Could not load "streaming-markdown" peer dep; markdown rendering disabled. Install it or inject globalThis.__smd.',
        err,
      )
    }
    return null
  }
}

/**
 * Reusable smd.js streaming markdown parser with rAF-batched writes.
 *
 * Lifecycle: init(container) → write(text)* → finalize()
 *
 * smd is resolved lazily — via globalThis.__smd (consumer-injected) or a
 * dynamic import of the optional `streaming-markdown` peer dependency.
 * If the peer dep cannot be resolved, the composable logs a one-time warning
 * and discards writes; the internal `smd`/`SmdModule` identifiers are the
 * historical module alias for the streaming-markdown package.
 *
 * @param options.onFlush - called after each rAF batch is flushed (e.g. scroll-to-bottom)
 * @param options.maxPendingChars - cap for the pre-init buffer (default 1M chars)
 */
export function useStreamingParser(
  options: UseStreamingParserOptions = {},
): UseStreamingParserReturn {
  const maxPending = options.maxPendingChars ?? DEFAULT_MAX_PENDING
  let smd: SmdModule | null = null
  let parser: unknown = null
  let pending: string[] = []
  let pendingChars = 0
  let rafId: number | null = null
  let initToken = 0

  function flush() {
    rafId = null
    if (!smd || !parser || pending.length === 0) return
    const text = pending.join('')
    pending = []
    pendingChars = 0
    try {
      smd.parser_write(parser, text)
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('[useStreamingParser] parser_write threw; chunk discarded', err)
    }
    options.onFlush?.()
  }

  function init(container: HTMLElement) {
    destroy()
    container.textContent = ''
    const token = ++initToken
    resolveSmd()
      .then((resolved) => {
        if (token !== initToken) return
        if (!resolved) return
        smd = resolved
        const renderer = resolved.default_renderer(container)
        parser = resolved.parser(renderer)
        if (pending.length > 0) {
          const text = pending.join('')
          pending = []
          pendingChars = 0
          try {
            resolved.parser_write(parser, text)
          } catch (err) {
            // eslint-disable-next-line no-console
            console.error('[useStreamingParser] initial parser_write threw; buffered chunk discarded', err)
          }
        }
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error('[useStreamingParser] resolveSmd unexpectedly rejected', err)
      })
  }

  function write(text: string) {
    if (initToken === 0) return
    if (pendingChars + text.length > maxPending) {
      // eslint-disable-next-line no-console
      console.warn(
        '[useStreamingParser] dropping write — pending buffer exceeded maxPendingChars (%d). smd may never have resolved.',
        maxPending,
      )
      return
    }
    pending.push(text)
    pendingChars += text.length
    if (rafId === null && typeof requestAnimationFrame !== 'undefined') {
      rafId = requestAnimationFrame(flush)
    } else if (rafId === null) {
      queueMicrotask(flush)
    }
  }

  function finalize() {
    if (rafId !== null) {
      if (typeof cancelAnimationFrame !== 'undefined') cancelAnimationFrame(rafId)
      rafId = null
    }
    if (pending.length > 0) flush()
    if (smd && parser) {
      try {
        smd.parser_end(parser)
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error('[useStreamingParser] parser_end threw', err)
      }
    }
    parser = null
    smd = null
  }

  function destroy() {
    finalize()
  }

  return { init, write, finalize, destroy }
}
