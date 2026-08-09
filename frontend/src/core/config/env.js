// Next.js/webpack only inlines NEXT_PUBLIC_* values into the client bundle
// when they're accessed as a literal, static `process.env.NEXT_PUBLIC_X`
// expression — that's a build-time textual substitution, not a real
// runtime env lookup in the browser. A dynamic/computed access like
// `process.env[key]` (as a previous version of this file used, via a
// shared readEnv(key, fallback) helper) is invisible to that substitution
// step: it survives into the browser bundle unresolved, where `process.env`
// is not a populated object, so the lookup evaluates to undefined and
// silently falls through to the hardcoded default — regardless of what's
// actually set in the hosting platform's environment variables. Every
// NEXT_PUBLIC_* reference below must stay a literal dotted expression for
// exactly that reason; do not reintroduce a keyed/dynamic helper here.
export const env = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',
  apiVersion: process.env.NEXT_PUBLIC_API_VERSION || 'v1',
  appName: process.env.NEXT_PUBLIC_APP_NAME || 'Zainab Rafique Hospital',
  isProduction: process.env.NODE_ENV === 'production',
};
