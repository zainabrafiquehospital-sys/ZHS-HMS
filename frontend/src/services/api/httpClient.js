import axios from 'axios';
import { env } from '@/core/config/env';
import {
  clearAccessToken,
  clearUserId,
  getAccessToken,
  getUserId,
  setAccessToken,
  setUserId,
} from '@/services/api/tokenStore';

export const httpClient = axios.create({
  baseURL: `${env.apiBaseUrl}/api/${env.apiVersion}`,
  timeout: 15000,
  // The refresh token travels as an httpOnly cookie scoped to
  // /api/v1/auth (see backend/app/modules/auth/router.py) — the browser
  // only attaches it automatically when the request opts into sending
  // credentials cross-origin.
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Paths that must never trigger the 401 -> refresh -> retry flow below —
// a 401 from `/auth/refresh` itself means the session is genuinely gone
// (no valid cookie), not something a second refresh attempt could fix,
// and retrying `/auth/login`'s own 401 (wrong password) would be
// nonsensical.
const _AUTH_ENDPOINTS_EXEMPT_FROM_REFRESH = ['/auth/login', '/auth/refresh', '/auth/logout'];

let _onAuthFailure = null;
/** Registered once by AuthProvider on mount — called when a refresh
 * attempt definitively fails, so the app can clear user state and
 * redirect to /login. Kept outside React so this plain Axios module
 * never needs to import React/context machinery. */
export function setOnAuthFailure(callback) {
  _onAuthFailure = callback;
}

let _refreshPromise = null;
/** Coalesces concurrent 401s into a single `/auth/refresh` call — several
 * requests can legitimately be in flight the instant an access token
 * expires; without this they would each fire their own refresh call
 * and race to rotate the same refresh-token family. The `.finally()`
 * below already resets `_refreshPromise` to `null` on *either* outcome
 * (a successful rotation, a genuine 401/403, or a transient network
 * failure) — so a failed-due-to-network attempt never leaves this
 * singleton stuck; the very next 401 anywhere still starts a brand-new
 * refresh attempt, no separate reset needed. */
function _refreshAccessToken() {
  if (!_refreshPromise) {
    // See tokenStore.js's `userId` docstring — this lets the backend
    // detect a stale-cookie cross-tab identity swap and fail the
    // refresh cleanly instead of silently authenticating this tab as
    // whoever's login most recently overwrote the shared browser
    // cookie. `undefined` (no header) when this tab has never known a
    // user id yet (e.g. the very first refresh on a hard reload) —
    // that case must trust the cookie exactly as before.
    const expectedUserId = getUserId();
    _refreshPromise = httpClient
      .post(
        '/auth/refresh',
        undefined,
        expectedUserId ? { headers: { 'X-Expected-User-Id': expectedUserId } } : undefined,
      )
      .then((data) => {
        setAccessToken(data.data.access_token);
        setUserId(data.data.user.id);
        return data.data.access_token;
      })
      .finally(() => {
        _refreshPromise = null;
      });
  }
  return _refreshPromise;
}

httpClient.interceptors.request.use((config) => {
  config.headers['X-Correlation-Id'] =
    globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

httpClient.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const originalRequest = error.config;
    const isExemptFromRefresh = _AUTH_ENDPOINTS_EXEMPT_FROM_REFRESH.some((path) =>
      originalRequest?.url?.includes(path),
    );

    if (error.response?.status === 401 && !isExemptFromRefresh && !originalRequest._retried) {
      originalRequest._retried = true;
      try {
        const newToken = await _refreshAccessToken();
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return httpClient(originalRequest);
      } catch (refreshError) {
        // Only a definitive "this refresh token is actually invalid"
        // answer from the server (401/403) means the session is really
        // gone — clear it and force a fresh login. Any other failure
        // shape (a timeout, a dropped connection, a request the browser
        // deferred/aborted while the tab was backgrounded) is
        // inconclusive, not proof the refresh cookie is bad — a
        // backgrounded tab's own polling hooks (refetchIntervalInBackground:
        // true, see useConsultation.js/useInventory.js/useVitals.js) keep
        // firing while hidden, and a burst of them landing right as the
        // tab regains connectivity can transiently time out. Treating
        // that identically to a real invalid session was the root cause
        // of a confirmed bug: users were force-logged-out after
        // backgrounding/switching tabs even though their refresh cookie
        // was still perfectly valid. Leaving the session intact here
        // means the *next* request gets a fresh chance to refresh once
        // connectivity is back — this request still fails normally for
        // its own caller either way, via the fall-through below.
        //
        // `refreshError` here is NOT a raw axios error with a
        // `.response` — `_refreshAccessToken()` makes its `/auth/refresh`
        // call through this same shared `httpClient`, so it already
        // passed through this very interceptor and was normalized to
        // `{code, message, details, status}` below before ever reaching
        // this catch (see the `normalized` rejection at the bottom of
        // this handler: `/auth/refresh` is itself exempt from the
        // retry-loop above, but not from that final normalization step).
        // A real HTTP error status survives that normalization as
        // `status`; a network/timeout failure normalizes to `status:
        // null` (there was never an `error.response` to read a status
        // from) — that's the exact signal this check relies on.
        if (refreshError?.status === 401 || refreshError?.status === 403) {
          clearAccessToken();
          clearUserId();
          _onAuthFailure?.();
        }
        // fall through to the normalized rejection below using the
        // *original* 401, not the refresh call's own error shape.
      }
    }

    const normalized = {
      code: error.response?.data?.error?.code ?? 'NETWORK_ERROR',
      message: error.response?.data?.error?.message ?? error.message,
      details: error.response?.data?.error?.details ?? null,
      status: error.response?.status ?? null,
    };
    return Promise.reject(normalized);
  },
);
