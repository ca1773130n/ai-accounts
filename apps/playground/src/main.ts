import { createApp } from 'vue';
import App from './App.vue';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import { aiAccountsPlugin } from '@ai-accounts/vue-headless';
import '@ai-accounts/vue-styled/styles.css';

const client = new AiAccountsClient({ baseUrl: '' });

createApp(App).use(aiAccountsPlugin, { client }).mount('#app');
