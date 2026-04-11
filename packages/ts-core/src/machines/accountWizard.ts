import type { AiAccountsClient, BackendDTO, DetectResultDTO } from '../client';

export type WizardState =
  | 'idle'
  | 'picking_kind'
  | 'detecting'
  | 'entering_credential'
  | 'validating'
  | 'done'
  | 'error';

export interface AccountWizard {
  readonly state: WizardState;
  readonly kind: string | undefined;
  readonly detection: DetectResultDTO | undefined;
  readonly backend: BackendDTO | undefined;
  readonly error: string | undefined;
  subscribe(listener: () => void): () => void;
  start(): void;
  pickKind(kind: string): Promise<void>;
  submitCredential(flowKind: string, inputs: Record<string, string>): Promise<void>;
  reset(): void;
}

export interface CreateAccountWizardOptions {
  client: AiAccountsClient;
  defaultDisplayName?: string;
}

export function createAccountWizard(opts: CreateAccountWizardOptions): AccountWizard {
  const listeners = new Set<() => void>();
  const emit = () => listeners.forEach((l) => l());

  let state: WizardState = 'idle';
  let kind: string | undefined;
  let detection: DetectResultDTO | undefined;
  let backend: BackendDTO | undefined;
  let error: string | undefined;

  return {
    get state() {
      return state;
    },
    get kind() {
      return kind;
    },
    get detection() {
      return detection;
    },
    get backend() {
      return backend;
    },
    get error() {
      return error;
    },

    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    start() {
      state = 'picking_kind';
      kind = undefined;
      detection = undefined;
      backend = undefined;
      error = undefined;
      emit();
    },

    async pickKind(chosen) {
      kind = chosen;
      state = 'detecting';
      emit();
      try {
        backend = await opts.client.createBackend({
          kind: chosen,
          display_name: opts.defaultDisplayName ?? `${chosen} account`,
        });
        detection = await opts.client.detectBackend(backend.id);
        if (!detection.installed) {
          state = 'error';
          error = `${chosen} CLI is not installed on the host`;
          emit();
          return;
        }
        state = 'entering_credential';
      } catch (e) {
        state = 'error';
        error = e instanceof Error ? e.message : 'failed to create backend';
      }
      emit();
    },

    async submitCredential(flowKind, inputs) {
      if (!backend) {
        state = 'error';
        error = 'no backend in progress';
        emit();
        return;
      }
      state = 'validating';
      emit();
      try {
        await opts.client.loginBackend(backend.id, flowKind, inputs);
        backend = await opts.client.validateBackend(backend.id);
        state = 'done';
      } catch (e) {
        state = 'error';
        error = e instanceof Error ? e.message : 'validation failed';
      }
      emit();
    },

    reset() {
      state = 'idle';
      kind = undefined;
      detection = undefined;
      backend = undefined;
      error = undefined;
      emit();
    },
  };
}
