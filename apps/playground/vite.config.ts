import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 6173,
    strictPort: true,
    allowedHosts: ['burningxoul.mooo.com'],
    proxy: {
      '/api': 'http://localhost:30000',
      '/health': 'http://localhost:30000',
      '/schema': 'http://localhost:30000',
    },
  },
});
