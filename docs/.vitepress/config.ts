import { defineConfig } from 'vitepress';

export default defineConfig({
  title: 'ai-accounts',
  description: 'Reusable AI backend, chat, and PTY session package',
  themeConfig: {
    nav: [
      { text: 'Guide', link: '/guide/getting-started' },
      { text: 'Concepts', link: '/concepts/architecture' },
    ],
    sidebar: {
      '/guide/': [
        { text: 'Getting Started', link: '/guide/getting-started' },
      ],
      '/concepts/': [
        { text: 'Architecture', link: '/concepts/architecture' },
      ],
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/ca1773130n/ai-accounts' },
    ],
  },
});
