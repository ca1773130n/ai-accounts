import type {
  AiAccountsClient,
  BackendDTO,
  DetectResultDTO,
  OAuthDeviceLoginDTO,
  OnboardingStateDTO,
} from '../client';

export type OnboardingMachineState =
  | 'idle'
  | 'started'
  | 'detecting'
  | 'picking_kind'
  | 'entering_credential'
  | 'oauth_challenge'
  | 'oauth_polling'
  | 'validating'
  | 'done'
  | 'error';

export interface OnboardingFlowMachine {
  readonly state: OnboardingMachineState;
  readonly kinds: Array<{ id: string; detection: DetectResultDTO }> | undefined;
  readonly selectedKind: string | undefined;
  readonly selectedBackend: BackendDTO | undefined;
  readonly oauthChallenge: OAuthDeviceLoginDTO | undefined;
  readonly createdBackendId: string | undefined;
  readonly error: string | undefined;

  subscribe(listener: () => void): () => void;
  start(): Promise<void>;
  detect(): Promise<void>;
  pickKind(kind: string): Promise<void>;
  submitApiKey(apiKey: string): Promise<void>;
  submitOauthDevice(): Promise<void>;
  cancelOAuth(): void;
  reset(): void;
}

export interface CreateOnboardingFlowOptions {
  client: AiAccountsClient;
  pollIntervalMs?: number;
  timeoutMs?: number;
}

export function createOnboardingFlow(
  opts: CreateOnboardingFlowOptions
): OnboardingFlowMachine {
  const listeners = new Set<() => void>();
  const emit = () => listeners.forEach((l) => l());

  let state: OnboardingMachineState = 'idle';
  let onboardingId: string | undefined;
  let kinds: Array<{ id: string; detection: DetectResultDTO }> | undefined;
  let selectedKind: string | undefined;
  let selectedBackend: BackendDTO | undefined;
  let oauthChallenge: OAuthDeviceLoginDTO | undefined;
  let createdBackendId: string | undefined;
  let error: string | undefined;
  let pollCancelled = false;

  const pollIntervalMs = opts.pollIntervalMs ?? 2000;
  const timeoutMs = opts.timeoutMs ?? 15 * 60 * 1000;

  // suppress unused import warning — OnboardingStateDTO used as return type reference
  void (null as unknown as OnboardingStateDTO);

  function setError(msg: string) {
    state = 'error';
    error = msg;
    emit();
  }

  async function finalize() {
    if (!onboardingId) return;
    state = 'validating';
    emit();
    try {
      const final = await opts.client.finalizeOnboarding(onboardingId);
      createdBackendId = final.created_backend_id ?? undefined;
      state = 'done';
      emit();
    } catch (e) {
      setError((e as Error).message ?? 'finalize failed');
    }
  }

  function schedulePoll(handle: string) {
    pollCancelled = false;
    const deadline = Date.now() + timeoutMs;
    const tick = async () => {
      if (pollCancelled || state !== 'oauth_polling') return;
      if (Date.now() > deadline) {
        setError('OAuth login timed out');
        return;
      }
      if (!onboardingId) {
        setError('no onboarding session');
        return;
      }
      try {
        const result = await opts.client.pollOnboardingLogin(onboardingId, handle);
        if (pollCancelled || state !== 'oauth_polling') return;
        if (result.kind === 'complete') {
          await finalize();
          return;
        }
        setTimeout(tick, pollIntervalMs);
      } catch (e) {
        setError((e as Error).message ?? 'polling error');
      }
    };
    setTimeout(tick, pollIntervalMs);
  }

  return {
    get state() {
      return state;
    },
    get kinds() {
      return kinds;
    },
    get selectedKind() {
      return selectedKind;
    },
    get selectedBackend() {
      return selectedBackend;
    },
    get oauthChallenge() {
      return oauthChallenge;
    },
    get createdBackendId() {
      return createdBackendId;
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

    async start() {
      try {
        const session = await opts.client.startOnboarding();
        onboardingId = session.id;
        state = 'started';
        emit();
      } catch (e) {
        setError((e as Error).message ?? 'failed to start onboarding');
      }
    },

    async detect() {
      if (!onboardingId) {
        setError('not started');
        return;
      }
      state = 'detecting';
      emit();
      try {
        const detect = await opts.client.detectForOnboarding(onboardingId);
        kinds = Object.entries(detect.results).map(([id, detection]) => ({
          id,
          detection,
        }));
        state = 'picking_kind';
        emit();
      } catch (e) {
        setError((e as Error).message ?? 'detect failed');
      }
    },

    async pickKind(chosen) {
      if (!onboardingId) {
        setError('not started');
        return;
      }
      try {
        selectedBackend = await opts.client.pickOnboardingKind(
          onboardingId,
          chosen,
          `${chosen} account`
        );
        selectedKind = chosen;
        state = 'entering_credential';
        emit();
      } catch (e) {
        setError((e as Error).message ?? 'pickKind failed');
      }
    },

    async submitApiKey(apiKey) {
      if (!onboardingId) {
        setError('not started');
        return;
      }
      state = 'validating';
      emit();
      try {
        const response = await opts.client.beginOnboardingLogin(onboardingId, 'api_key', {
          api_key: apiKey,
        });
        if (response.kind !== 'complete') {
          setError('unexpected pending response from api_key flow');
          return;
        }
        await finalize();
      } catch (e) {
        setError((e as Error).message ?? 'login failed');
      }
    },

    async submitOauthDevice() {
      if (!onboardingId) {
        setError('not started');
        return;
      }
      state = 'oauth_challenge';
      emit();
      try {
        const response = await opts.client.beginOnboardingLogin(onboardingId, 'oauth_device', {});
        if (response.kind !== 'pending' || !response.oauth) {
          setError('expected pending OAuth response');
          return;
        }
        oauthChallenge = response.oauth;
        state = 'oauth_polling';
        emit();
        schedulePoll(response.oauth.handle);
      } catch (e) {
        setError((e as Error).message ?? 'OAuth start failed');
      }
    },

    cancelOAuth() {
      pollCancelled = true;
      state = 'entering_credential';
      oauthChallenge = undefined;
      emit();
    },

    reset() {
      pollCancelled = true;
      state = 'idle';
      onboardingId = undefined;
      kinds = undefined;
      selectedKind = undefined;
      selectedBackend = undefined;
      oauthChallenge = undefined;
      createdBackendId = undefined;
      error = undefined;
      emit();
    },
  };
}
