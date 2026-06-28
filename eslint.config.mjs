import js from '@eslint/js';
import tsparser from '@typescript-eslint/parser';
import tseslint from '@typescript-eslint/eslint-plugin';

/**
 * Flat ESLint config for the TypeScript packages in this workspace.
 *
 * Each package runs `eslint src`; ESLint resolves this root config by
 * walking up from the package directory. `.vue` single-file components
 * are intentionally excluded — no Vue ESLint parser/plugin is installed,
 * and their `<script>` blocks are already covered by `vue-tsc`.
 */
export default [
  {
    ignores: ['**/dist/**', '**/node_modules/**', '**/*.vue', '**/*.d.ts'],
  },
  {
    files: ['**/*.{ts,tsx,js,mjs,cjs}'],
    // Source files carry defensive `eslint-disable no-console` comments for
    // host projects that enable `no-console`; this workspace config does not,
    // so those directives read as "unused". Don't flag them.
    linterOptions: { reportUnusedDisableDirectives: 'off' },
    languageOptions: {
      parser: tsparser,
      ecmaVersion: 'latest',
      sourceType: 'module',
    },
    plugins: { '@typescript-eslint': tseslint },
    rules: {
      ...js.configs.recommended.rules,
      // TypeScript handles undefined-symbol resolution; the core rule
      // produces false positives on TS/ambient globals.
      'no-undef': 'off',
      // Defer unused-variable detection to the TS-aware rule so type-only
      // imports and `_`-prefixed intentional discards are handled correctly.
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' },
      ],
    },
  },
];
