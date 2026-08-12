import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

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
  },
});
