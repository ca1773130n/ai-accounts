import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    // Override with AIA_WEB_PORT (e.g. when serving the playground behind a
    // tunnel/domain on a fixed port); defaults to 6173 for local dev.
    port: Number(process.env.AIA_WEB_PORT) || 6173,
    strictPort: true,
    allowedHosts: ['burningxoul.mooo.com'],
    proxy: {
      '/api': 'http://localhost:30000',
      '/health': 'http://localhost:30000',
      '/schema': 'http://localhost:30000',
    },
  },
});
