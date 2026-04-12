import { ref, type Ref } from 'vue';
import type { AiAccountsClient } from '@ai-accounts/ts-core';
import { PtySocket } from '@ai-accounts/ts-core';

export interface UsePtySessionReturn {
  sessionId: Ref<string | null>;
  isConnected: Ref<boolean>;
  error: Ref<string | null>;
  spawn: (backendId: string, command: string[], cols?: number, rows?: number) => Promise<void>;
  write: (data: Uint8Array) => void;
  resize: (cols: number, rows: number) => Promise<void>;
  kill: () => Promise<void>;
  onData: (cb: (data: Uint8Array) => void) => void;
}

export function usePtySession(client: AiAccountsClient): UsePtySessionReturn {
  const sessionId = ref<string | null>(null);
  const isConnected = ref(false);
  const error = ref<string | null>(null);
  let socket: PtySocket | null = null;
  let dataCallback: ((data: Uint8Array) => void) | null = null;

  function onData(cb: (data: Uint8Array) => void) {
    dataCallback = cb;
  }

  async function spawn(backendId: string, command: string[], cols = 80, rows = 24) {
    error.value = null;
    const result = await (client as any).spawnPty({
      backend_id: backendId,
      command,
      cols,
      rows,
    });
    sessionId.value = result.session_id;
    const wsUrl = (client as any).ptyWebSocketUrl(result.session_id);
    socket = new PtySocket({
      url: wsUrl,
      onData: (data) => dataCallback?.(data),
      onClose: () => {
        isConnected.value = false;
      },
      onError: () => {
        error.value = 'WebSocket error';
      },
      reconnectMs: 3000,
    });
    isConnected.value = true;
  }

  function write(data: Uint8Array) {
    socket?.send(data);
  }

  async function resize(cols: number, rows: number) {
    if (sessionId.value) {
      await (client as any).resizePty(sessionId.value, cols, rows);
    }
  }

  async function kill() {
    if (sessionId.value) {
      await (client as any).killPty(sessionId.value);
    }
    socket?.close();
    socket = null;
    sessionId.value = null;
    isConnected.value = false;
  }

  return { sessionId, isConnected, error, spawn, write, resize, kill, onData };
}
