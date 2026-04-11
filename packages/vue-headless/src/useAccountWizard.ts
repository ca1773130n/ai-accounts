import { ref, type Ref } from 'vue';
import {
  createAccountWizard,
  type AiAccountsClient,
  type BackendDTO,
  type DetectResultDTO,
  type WizardState,
} from '@ai-accounts/ts-core';

export interface UseAccountWizardOptions {
  client: AiAccountsClient;
  defaultDisplayName?: string;
}

export interface UseAccountWizardReturn {
  state: Ref<WizardState>;
  kind: Ref<string | undefined>;
  detection: Ref<DetectResultDTO | undefined>;
  backend: Ref<BackendDTO | undefined>;
  error: Ref<string | undefined>;
  start: () => void;
  pickKind: (kind: string) => Promise<void>;
  submitCredential: (flowKind: string, inputs: Record<string, string>) => Promise<void>;
  reset: () => void;
}

export function useAccountWizard(
  options: UseAccountWizardOptions
): UseAccountWizardReturn {
  const wizardOpts: import('@ai-accounts/ts-core').CreateAccountWizardOptions = {
    client: options.client,
    ...(options.defaultDisplayName !== undefined
      ? { defaultDisplayName: options.defaultDisplayName }
      : {}),
  };
  const machine = createAccountWizard(wizardOpts);

  const state = ref<WizardState>(machine.state);
  const kind = ref<string | undefined>(machine.kind);
  const detection = ref<DetectResultDTO | undefined>(machine.detection);
  const backend = ref<BackendDTO | undefined>(machine.backend);
  const error = ref<string | undefined>(machine.error);

  machine.subscribe(() => {
    state.value = machine.state;
    kind.value = machine.kind;
    detection.value = machine.detection;
    backend.value = machine.backend;
    error.value = machine.error;
  });

  return {
    state,
    kind,
    detection,
    backend,
    error,
    start: () => machine.start(),
    pickKind: (k) => machine.pickKind(k),
    submitCredential: (fk, inp) => machine.submitCredential(fk, inp),
    reset: () => machine.reset(),
  };
}
