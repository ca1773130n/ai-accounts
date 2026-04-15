export interface UseStreamingParserOptions {
  onFlush?: () => void
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

async function resolveSmd(): Promise<SmdModule | null> {
  // 1. globalThis.__smd (consumer-injected)
  const injected = (globalThis as Record<string, unknown>).__smd
  if (injected) return injected as SmdModule
  // 2. dynamic import — optional peerDep
  try {
    // @ts-expect-error - streaming-markdown is an optional peer dep; may not be installed or typed
    const mod = (await import(/* @vite-ignore */ 'streaming-markdown')) as unknown
    return mod as SmdModule
  } catch {
    return null
  }
}

/**
 * Reusable smd.js streaming markdown parser with rAF-batched writes.
 *
 * Lifecycle: init(container) → write(text)* → finalize()
 *
 * smd is resolved lazily — via globalThis.__smd (consumer-injected) or a
 * dynamic import of the optional `smd` peer dependency. If smd cannot be
 * resolved, the composable degrades gracefully: writes are discarded, no
 * errors are thrown.
 *
 * @param options.onFlush - called after each rAF batch is flushed (e.g. scroll-to-bottom)
 */
export function useStreamingParser(
  options: UseStreamingParserOptions = {},
): UseStreamingParserReturn {
  let smd: SmdModule | null = null
  let parser: unknown = null
  let pending: string[] = []
  let rafId: number | null = null
  let initToken = 0

  function flush() {
    rafId = null
    if (!smd || !parser || pending.length === 0) return
    const text = pending.join('')
    pending = []
    try {
      smd.parser_write(parser, text)
    } catch {
      // parser may have been ended
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
          try {
            resolved.parser_write(parser, text)
          } catch {
            // noop
          }
        }
      })
      .catch(() => {
        // swallow
      })
  }

  function write(text: string) {
    if (initToken === 0) return // never initialized
    pending.push(text)
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
      } catch {
        // already ended
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
