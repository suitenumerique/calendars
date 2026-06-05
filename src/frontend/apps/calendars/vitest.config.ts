import { defineConfig } from "vitest/config";
import path from "node:path";

// NOTE: `jsdom` is declared in src/frontend/package.json (the npm workspace
// root), not in apps/calendars/package.json. That forces npm to hoist it to
// node_modules/ alongside vitest. Vitest spawns workers that resolve `jsdom`
// from its own location; without the root-level dep, jsdom lands under
// apps/calendars/node_modules and the worker fails with ERR_MODULE_NOT_FOUND.

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
