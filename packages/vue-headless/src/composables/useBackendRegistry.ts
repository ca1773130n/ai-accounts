import { ref, type Ref } from 'vue';
import type { BackendMetadata } from '@ai-accounts/ts-core';
import { useAiAccounts } from './useAiAccounts';

type Registry = {
  backends: Ref<BackendMetadata[]>;
  loaded: Ref<boolean>;
  load: () => Promise<void>;
  get: (kind: string) => BackendMetadata | undefined;
};

export function useBackendRegistry(): Registry {
  const { client } = useAiAccounts();
  const backends = ref<BackendMetadata[]>([]);
  const loaded = ref(false);

  async function load() {
    const result = await client.getBackendMetadata();
    backends.value = result.items;
    loaded.value = true;
  }

  function get(kind: string): BackendMetadata | undefined {
    return backends.value.find((m) => m.kind === kind);
  }

  return { backends, loaded, load, get };
}
