import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:20000',
      '/health': 'http://localhost:20000',
      '/schema': 'http://localhost:20000',
    },
  },
});
