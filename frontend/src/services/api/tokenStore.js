/**
 * Holds the current access token in memory only — never localStorage or
 * sessionStorage. The refresh token is an httpOnly, SameSite=Strict
 * cookie the backend sets and reads directly (see
 * backend/app/modules/auth/router.py's module docstring); the frontend
 * never sees its value at all. Keeping the short-lived access token
 * out of any JS-readable storage means an XSS payload can steal at
 * worst a 15-minute-lived token already in scope, never a durable
 * credential — this is a deliberate security choice, not an oversight
 * that "forgot" to persist across a hard page reload (a hard reload
 * re-runs the silent refresh-on-load flow in AuthProvider instead).
 */
let accessToken = null;

export function getAccessToken() {
  return accessToken;
}

export function setAccessToken(token) {
  accessToken = token;
}

export function clearAccessToken() {
  accessToken = null;
}
