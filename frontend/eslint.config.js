import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

// Flat config (ESLint 9). 迁移期务实取向：类型检查交给 tsc，本配置聚焦
// react-hooks 正确性 + 明显死代码；no-explicit-any 在收紧 noImplicitAny 前先关。
export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', 'smoke.cjs', '*.config.js', '*.config.ts'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // TS 自己查未定义变量，关掉 eslint no-undef 避免对浏览器全局误报
      'no-undef': 'off',
      // 迁移期放宽，与 tsconfig noImplicitAny=false 对齐；收紧类型后再打开
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'react-refresh/only-export-components': 'off',
    },
  },
);
