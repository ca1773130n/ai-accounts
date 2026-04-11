import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';

export default defineConfig({
  plugins: [vue()],
  build: {
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      name: 'AiAccountsVueStyled',
      formats: ['es', 'cjs'],
      fileName: (format) =>
        `ai-accounts-vue-styled.${format === 'es' ? 'js' : 'cjs.js'}`,
    },
    rollupOptions: {
      external: ['vue', '@ai-accounts/ts-core', '@ai-accounts/vue-headless'],
      output: {
        globals: { vue: 'Vue' },
        assetFileNames: (assetInfo) => {
          if (assetInfo.name === 'style.css') return 'styles.css';
          return assetInfo.name ?? 'asset';
        },
      },
    },
  },
});
