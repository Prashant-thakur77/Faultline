import path from "node:path";
import { defineConfig } from "vitest/config";

// Component tests (npm test): happy-dom + Testing Library, no browser. Real components, real
// rendering; only fetch is stubbed per test (the backend contract is covered by the live tests).
export default defineConfig({
  esbuild: { jsx: "automatic" },
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: {
    environment: "happy-dom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    restoreMocks: true,
  },
});
