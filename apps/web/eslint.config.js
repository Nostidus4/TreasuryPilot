import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const tokenBans = [
  [
    String.raw`text-\[\d+px\]`,
    'Use the type scale (text-xs … text-display), not a pixel font size.',
  ],
  [
    String.raw`rounded-\[\d+px\]`,
    'Use rounded-sm, rounded-md or rounded-lg from the token scale.',
  ],
  [
    String.raw`-\[#[0-9a-fA-F]{3,8}\]`,
    'Use a colour token (bg-surface, text-danger …), not a hex value.',
  ],
];

const designTokenRules = tokenBans.flatMap(([pattern, message]) => [
  { selector: `Literal[value=/${pattern}/]`, message },
  { selector: `TemplateElement[value.raw=/${pattern}/]`, message },
]);

export default tseslint.config(
  {
    ignores: ['dist', 'src/lib/api/schema.d.ts', 'public/mockServiceWorker.js'],
  },
  {
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommendedTypeChecked,
    ],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        project: ['./tsconfig.app.json', './tsconfig.node.json'],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      // UI refactor plan section 9: sizes, radii and colours come from tokens.
      'no-restricted-syntax': ['error', ...designTokenRules],
    },
  },
);
