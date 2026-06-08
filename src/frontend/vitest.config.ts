import { defineConfig } from "vitest/config";
import path from "node:path";

// NOTE: `jsdom` must stay in this package's devDependencies so vitest's
// worker processes can resolve it (they fail with ERR_MODULE_NOT_FOUND
// otherwise).

export default defineConfig({
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: [],
    include: ["**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      reportsDirectory: ".coverage",
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Keep parity with vite.config.mts so tests see NEXT_PUBLIC_* via
  // import.meta.env.
  envPrefix: "NEXT_PUBLIC_",
});
