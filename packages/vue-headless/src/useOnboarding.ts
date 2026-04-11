import { ref, type Ref } from 'vue';
import {
  createOnboardingFlow,
  type AiAccountsClient,
  type BackendDTO,
  type CreateOnboardingFlowOptions,
  type DetectResultDTO,
  type OAuthDeviceLoginDTO,
  type OnboardingFlowMachine,
  type OnboardingMachineState,
} from '@ai-accounts/ts-core';

export interface UseOnboardingOptions {
  client: AiAccountsClient;
  pollIntervalMs?: number;
}

export interface UseOnboardingReturn {
  state: Ref<OnboardingMachineState>;
  kinds: Ref<Array<{ id: string; detection: DetectResultDTO }> | undefined>;
  selectedKind: Ref<string | undefined>;
  selectedBackend: Ref<BackendDTO | undefined>;
  oauthChallenge: Ref<OAuthDeviceLoginDTO | undefined>;
  createdBackendId: Ref<string | undefined>;
  error: Ref<string | undefined>;
  start: () => Promise<void>;
  detect: () => Promise<void>;
  pickKind: (kind: string) => Promise<void>;
  submitApiKey: (apiKey: string) => Promise<void>;
  submitOauthDevice: () => Promise<void>;
  cancelOAuth: () => void;
  reset: () => void;
}

export function useOnboarding(options: UseOnboardingOptions): UseOnboardingReturn {
  const machineOpts: CreateOnboardingFlowOptions = {
    client: options.client,
    ...(options.pollIntervalMs !== undefined ? { pollIntervalMs: options.pollIntervalMs } : {}),
  };
  const machine: OnboardingFlowMachine = createOnboardingFlow(machineOpts);

  const state = ref<OnboardingMachineState>(machine.state);
  const kinds = ref<Array<{ id: string; detection: DetectResultDTO }> | undefined>(machine.kinds);
  const selectedKind = ref<string | undefined>(machine.selectedKind);
  const selectedBackend = ref<BackendDTO | undefined>(machine.selectedBackend);
  const oauthChallenge = ref<OAuthDeviceLoginDTO | undefined>(machine.oauthChallenge);
  const createdBackendId = ref<string | undefined>(machine.createdBackendId);
  const error = ref<string | undefined>(machine.error);

  machine.subscribe(() => {
    state.value = machine.state;
    kinds.value = machine.kinds;
    selectedKind.value = machine.selectedKind;
    selectedBackend.value = machine.selectedBackend;
    oauthChallenge.value = machine.oauthChallenge;
    createdBackendId.value = machine.createdBackendId;
    error.value = machine.error;
  });

  return {
    state,
    kinds,
    selectedKind,
    selectedBackend,
    oauthChallenge,
    createdBackendId,
    error,
    start: () => machine.start(),
    detect: () => machine.detect(),
    pickKind: (k) => machine.pickKind(k),
    submitApiKey: (k) => machine.submitApiKey(k),
    submitOauthDevice: () => machine.submitOauthDevice(),
    cancelOAuth: () => machine.cancelOAuth(),
    reset: () => machine.reset(),
  };
}
