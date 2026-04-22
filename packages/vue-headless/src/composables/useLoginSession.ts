import { ref, type Ref } from 'vue';
import type {
  LoginEvent,
  LoginFlowKind,
  MenuPrompt,
  TextPrompt,
  UrlPrompt,
} from '@ai-accounts/ts-core';
import { useAiAccounts } from './useAiAccounts';

export type LoginStatus = 'idle' | 'running' | 'complete' | 'failed' | 'cancelled';

export type UseLoginSession = {
  status: Ref<LoginStatus>;
  sessionId: Ref<string | null>;
  accountId: Ref<string | null>;
  urlPrompt: Ref<UrlPrompt | null>;
  textPrompt: Ref<TextPrompt | null>;
  menuPrompt: Ref<MenuPrompt | null>;
  stdoutLines: Ref<string[]>;
  errorCode: Ref<string | null>;
  errorMessage: Ref<string | null>;
  start: (
    accountId: string,
    flow: LoginFlowKind,
    inputs: Record<string, string>
  ) => Promise<void>;
  respond: (answer: string) => Promise<void>;
  /**
   * Write arbitrary text directly to the CLI's stdin. Used for eager
   * paste-code input before the CLI has emitted its own text prompt.
   */
  writeEager: (text: string) => Promise<void>;
  cancel: () => Promise<void>;
  /**
   * Return the composable to its initial idle state. Call this when
   * reusing the same session instance for a new login (e.g. the wizard's
   * "Add another account" flow) — otherwise `status` stays `'complete'`
   * from the prior login and the auto-start guard short-circuits.
   */
  reset: () => void;
};

export function useLoginSession(): UseLoginSession {
  const { client, emit } = useAiAccounts();
  const status = ref<LoginStatus>('idle');
  const sessionId = ref<string | null>(null);
  const accountId = ref<string | null>(null);
  const urlPrompt = ref<UrlPrompt | null>(null);
  const textPrompt = ref<TextPrompt | null>(null);
  const menuPrompt = ref<MenuPrompt | null>(null);
  const stdoutLines = ref<string[]>([]);
  const errorCode = ref<string | null>(null);
  const errorMessage = ref<string | null>(null);

  async function start(
    id: string,
    flow: LoginFlowKind,
    inputs: Record<string, string>
  ): Promise<void> {
    accountId.value = id;
    status.value = 'running';
    urlPrompt.value = null;
    textPrompt.value = null;
    menuPrompt.value = null;
    stdoutLines.value = [];
    errorCode.value = null;
    errorMessage.value = null;

    try {
      const { session_id } = await client.beginLogin(id, flow, inputs);
      sessionId.value = session_id;
      emit({ type: 'login.started', sessionId: session_id, backendKind: '', flow });

      for await (const event of client.streamLogin(id, session_id)) {
        dispatch(event);
        if (status.value !== 'running') return;
      }
      // Stream ended without a complete/failed event — treat as failure
      if (status.value === 'running') {
        status.value = 'failed';
        errorCode.value = 'stream_ended';
        errorMessage.value = 'Login stream ended unexpectedly';
      }
    } catch (err) {
      status.value = 'failed';
      errorCode.value = 'network_error';
      errorMessage.value = err instanceof Error ? err.message : String(err);
      emit({
        type: 'login.failed',
        sessionId: sessionId.value ?? '',
        code: 'network_error',
        message: errorMessage.value!,
      });
    }
  }

  function dispatch(event: LoginEvent) {
    switch (event.type) {
      case 'url_prompt':
        urlPrompt.value = event;
        emit({ type: 'login.prompt', sessionId: sessionId.value!, promptKind: 'url' });
        break;
      case 'text_prompt':
        textPrompt.value = event;
        emit({ type: 'login.prompt', sessionId: sessionId.value!, promptKind: 'text' });
        break;
      case 'menu_prompt':
        menuPrompt.value = event;
        emit({ type: 'login.prompt', sessionId: sessionId.value!, promptKind: 'menu' });
        break;
      case 'stdout':
        stdoutLines.value = [...stdoutLines.value, event.text];
        break;
      case 'progress':
        break;
      case 'complete':
        status.value = 'complete';
        accountId.value = event.account_id || accountId.value;
        emit({
          type: 'login.completed',
          sessionId: sessionId.value!,
          accountId: event.account_id,
        });
        break;
      case 'failed':
        status.value = 'failed';
        errorCode.value = event.code;
        errorMessage.value = event.message;
        emit({
          type: 'login.failed',
          sessionId: sessionId.value!,
          code: event.code,
          message: event.message,
        });
        break;
    }
  }

  async function respond(answer: string): Promise<void> {
    if (!sessionId.value || !accountId.value) return;
    const activePrompt = textPrompt.value ?? menuPrompt.value;
    if (!activePrompt) return;
    const promptId = activePrompt.prompt_id;
    textPrompt.value = null;
    menuPrompt.value = null;
    await client.respondLogin(accountId.value, sessionId.value, promptId, answer);
  }

  async function writeEager(text: string): Promise<void> {
    if (!sessionId.value || !accountId.value) return;
    await client.writeEagerLogin(accountId.value, sessionId.value, text);
  }

  async function cancel(): Promise<void> {
    if (!sessionId.value || !accountId.value) return;
    await client.cancelLogin(accountId.value, sessionId.value);
    status.value = 'cancelled';
  }

  function reset(): void {
    status.value = 'idle';
    sessionId.value = null;
    accountId.value = null;
    urlPrompt.value = null;
    textPrompt.value = null;
    menuPrompt.value = null;
    stdoutLines.value = [];
    errorCode.value = null;
    errorMessage.value = null;
  }

  return {
    status,
    sessionId,
    accountId,
    urlPrompt,
    textPrompt,
    menuPrompt,
    stdoutLines,
    errorCode,
    errorMessage,
    start,
    respond,
    writeEager,
    cancel,
    reset,
  };
}
