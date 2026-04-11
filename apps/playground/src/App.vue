<script setup lang="ts">
import { ref } from 'vue';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import { OnboardingFlow } from '@ai-accounts/vue-styled';

const client = new AiAccountsClient({ baseUrl: '' });
const doneId = ref<string | null>(null);

function onDone(id: string) {
  doneId.value = id;
}
</script>

<template>
  <main class="playground">
    <h1>ai-accounts playground</h1>
    <p class="intro">
      Full onboarding flow for AI backends. Claude, OpenCode, Gemini, and
      Codex all registered. Gemini and Codex support both API key and
      browser login.
    </p>
    <OnboardingFlow :client="client" @done="onDone" />
    <p v-if="doneId" class="created">
      Ready backend: <code>{{ doneId }}</code>
    </p>
  </main>
</template>

<style>
.playground {
  max-width: 640px;
  margin: 60px auto;
  padding: 0 20px;
  color: var(--aia-fg, #fafafa);
  font-family: var(--aia-font-sans, system-ui, sans-serif);
}

.playground h1 {
  font-size: 2rem;
  margin-bottom: 1rem;
}

.playground .intro {
  color: var(--aia-fg-muted, #a1a1aa);
  margin-bottom: 2rem;
  line-height: 1.6;
}

.playground code {
  font-family: var(--aia-font-mono, monospace);
  background: var(--aia-bg-elevated, #141414);
  padding: 2px 6px;
  border-radius: 4px;
}

.playground .created {
  margin-top: 2rem;
  color: var(--aia-success, #10b981);
}
</style>
