import { ref, type Ref } from 'vue';
import type {
  LoginEvent,
  LoginFlowKind,
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
  stdoutLines: Ref<string[]>;
  errorCode: Ref<string | null>;
  errorMessage: Ref<string | null>;
  start: (
    accountId: string,
    flow: LoginFlowKind,
    inputs: Record<string, string>
  ) => Promise<void>;
  respond: (answer: string) => Promise<void>;
  cancel: () => Promise<void>;
};

export function useLoginSession(): UseLoginSession {
  const { client, emit } = useAiAccounts();
  const status = ref<LoginStatus>('idle');
  const sessionId = ref<string | null>(null);
  const accountId = ref<string | null>(null);
  const urlPrompt = ref<UrlPrompt | null>(null);
  const textPrompt = ref<TextPrompt | null>(null);
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
    stdoutLines.value = [];
    errorCode.value = null;
    errorMessage.value = null;

    const { session_id } = await client.beginLogin(id, flow, inputs);
    sessionId.value = session_id;
    emit({ type: 'login.started', sessionId: session_id, backendKind: '', flow });

    for await (const event of client.streamLogin(id, session_id)) {
      dispatch(event);
      if (status.value !== 'running') return;
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
    if (!sessionId.value || !accountId.value || !textPrompt.value) return;
    const promptId = textPrompt.value.prompt_id;
    textPrompt.value = null;
    await client.respondLogin(accountId.value, sessionId.value, promptId, answer);
  }

  async function cancel(): Promise<void> {
    if (!sessionId.value || !accountId.value) return;
    await client.cancelLogin(accountId.value, sessionId.value);
    status.value = 'cancelled';
  }

  return {
    status,
    sessionId,
    accountId,
    urlPrompt,
    textPrompt,
    stdoutLines,
    errorCode,
    errorMessage,
    start,
    respond,
    cancel,
  };
}
