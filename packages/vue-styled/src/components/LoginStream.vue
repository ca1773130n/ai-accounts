<script setup lang="ts">
import { ref, watch } from 'vue';
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

async function selectMenuOption(number: number) {
  await props.session.respond(String(number));
}

// Auto-open OAuth URLs in the user's browser when they arrive
let lastOpenedUrl = '';
watch(
  () => props.session.urlPrompt.value?.url,
  (url) => {
    if (url && url !== lastOpenedUrl) {
      lastOpenedUrl = url;
      window.open(url, '_blank', 'noopener');
    }
  },
  { immediate: true },
);
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

    <div v-if="session.menuPrompt.value" class="aia-menu-prompt">
      <p class="aia-label">{{ session.menuPrompt.value.prompt }}</p>
      <div class="aia-menu-options">
        <button
          v-for="opt in session.menuPrompt.value.options"
          :key="opt.number"
          type="button"
          class="aia-menu-option"
          @click="selectMenuOption(opt.number)"
        >
          <span class="aia-menu-option__label">{{ opt.label }}</span>
          <span v-if="opt.description" class="aia-menu-option__desc">{{ opt.description }}</span>
        </button>
      </div>
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
.aia-menu-prompt .aia-label { font-weight: 500; margin-bottom: 0.5rem; }
.aia-menu-options { display: flex; flex-direction: column; gap: 0.5rem; }
.aia-menu-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 0.75rem 1rem;
  border: 1px solid var(--aia-color-border, #d0d0d0);
  border-radius: var(--aia-radius-md, 8px);
  background: var(--aia-color-surface, #fff);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, background 0.15s;
}
.aia-menu-option:hover {
  border-color: var(--aia-color-primary, #2563eb);
  background: var(--aia-color-surface-alt, #f7f7ff);
}
.aia-menu-option__label { font-weight: 500; }
.aia-menu-option__desc { font-size: 0.85em; color: var(--aia-color-text-muted, #666); margin-top: 0.2rem; }
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
