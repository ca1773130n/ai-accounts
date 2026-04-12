<script setup lang="ts">
import { ref } from 'vue';
import type { UseLoginSession } from '@ai-accounts/vue-headless';

const props = withDefaults(
  defineProps<{
    session: UseLoginSession;
    showStdout?: boolean;
  }>(),
  { showStdout: true }
);

const answer = ref('');

async function submit() {
  const value = answer.value;
  answer.value = '';
  await props.session.respond(value);
}
</script>

<template>
  <div class="aia-login-stream">
    <div v-if="session.urlPrompt.value" class="aia-url-prompt">
      <p class="aia-label">Open this URL to authenticate:</p>
      <a :href="session.urlPrompt.value.url" target="_blank" rel="noopener">
        {{ session.urlPrompt.value.url }}
      </a>
      <p v-if="session.urlPrompt.value.user_code" class="aia-code">
        Code: <code>{{ session.urlPrompt.value.user_code }}</code>
      </p>
    </div>

    <form v-if="session.textPrompt.value" class="aia-text-prompt" @submit.prevent="submit">
      <label>
        {{ session.textPrompt.value.prompt }}
        <input
          v-model="answer"
          :type="session.textPrompt.value.hidden ? 'password' : 'text'"
          autocomplete="off"
        />
      </label>
      <button type="submit">Continue</button>
    </form>

    <pre v-if="showStdout && session.stdoutLines.value.length > 0" class="aia-stdout">{{
      session.stdoutLines.value.join('')
    }}</pre>

    <div v-if="session.status.value === 'failed'" class="aia-error">
      <strong>{{ session.errorCode.value }}</strong>
      <p>{{ session.errorMessage.value }}</p>
    </div>

    <button
      v-if="session.status.value === 'running'"
      type="button"
      class="aia-cancel"
      @click="session.cancel()"
    >
      Cancel
    </button>
  </div>
</template>

<style scoped>
.aia-login-stream { display: flex; flex-direction: column; gap: 1rem; }
.aia-url-prompt a { word-break: break-all; }
.aia-code code { font-family: var(--aia-font-mono, monospace); font-size: 1.2em; }
.aia-stdout {
  background: var(--aia-stdout-bg, #111);
  color: var(--aia-stdout-fg, #eee);
  padding: 0.75rem;
  max-height: 240px;
  overflow: auto;
  font-family: var(--aia-font-mono, monospace);
  font-size: 0.85em;
}
.aia-error { color: var(--aia-error, #c00); }
</style>
