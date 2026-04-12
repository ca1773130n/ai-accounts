export interface PtySocketOptions {
  url: string;
  onData: (data: Uint8Array) => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  reconnectMs?: number;
}

export class PtySocket {
  private ws: WebSocket | null = null;
  private readonly opts: PtySocketOptions;
  private closed = false;

  constructor(opts: PtySocketOptions) {
    this.opts = opts;
    this.connect();
  }

  private connect() {
    if (this.closed) return;
    this.ws = new WebSocket(this.opts.url);
    this.ws.binaryType = 'arraybuffer';

    this.ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        this.opts.onData(new Uint8Array(event.data));
      }
    };

    this.ws.onclose = () => {
      if (!this.closed && this.opts.reconnectMs) {
        setTimeout(() => this.connect(), this.opts.reconnectMs);
      }
      this.opts.onClose?.();
    };

    this.ws.onerror = (e) => {
      this.opts.onError?.(e);
    };
  }

  send(data: Uint8Array): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(data);
    }
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
    this.ws = null;
  }
}
