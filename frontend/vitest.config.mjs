import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { configDefaults, defineConfig } from 'vitest/config';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Mirrors jsconfig.json's `@/*` path aliases — Vitest doesn't read
// jsconfig.json itself, so this is the one place both must be kept in
// sync (only `@` -> `./src` is actually needed for now; the same
// resolution covers every `@/xxx/*` sub-alias jsconfig.json declares).
export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'node',
    // e2e/ holds standalone Playwright scripts (raw chromium.launch()
    // automation against a running dev stack, no describe/it blocks —
    // see e2e/consultation-vitals-refetch.spec.js's own docstring) —
    // not Vitest suites, even though their `.spec.js` naming would
    // otherwise match Vitest's default test glob.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
});
