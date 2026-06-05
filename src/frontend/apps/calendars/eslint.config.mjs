import { defineConfig, globalIgnores } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

const eslintConfig = defineConfig([
  globalIgnores([
    "dist/**",
    "src/routes.gen.ts",
    "node_modules/**",
    "test-dst.js",
    "src/styles/cunningham-tokens.ts",
    "src/styles/cunningham-tokens-sass.scss",
  ]),
  ...tseslint.configs.recommended,
  reactHooks.configs.flat.recommended,
  {
    rules: {
      "react-hooks/exhaustive-deps": "off",
      "react-hooks/refs": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
      "@typescript-eslint/no-empty-object-type": "off",
    },
  },
]);

export default eslintConfig;
