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

/**
 * The id of the user this tab last authenticated as — kept alongside the
 * access token (same in-memory-only, per-tab storage, cleared on the
 * same events) purely so httpClient.js can send it as the
 * `X-Expected-User-Id` header on every `/auth/refresh` call. This closes
 * a cross-tab identity-bleed gap found in the 2026-08-19 audit: the
 * refresh cookie is scoped per-origin+path, not per-tab, so on a shared
 * front-desk machine, a second tab logging in as a different staff
 * member silently overwrites the one browser-wide cookie this tab's own
 * silent refresh depends on. Sending back "who I last knew myself to
 * be" lets the backend detect that mismatch and fail the refresh
 * cleanly (see AuthService.refresh's `expected_user_id` docstring)
 * instead of this tab silently becoming the other person. Never sent
 * anywhere except that one header; never displayed.
 */
let userId = null;

export function getUserId() {
  return userId;
}

export function setUserId(id) {
  userId = id;
}

export function clearUserId() {
  userId = null;
}
