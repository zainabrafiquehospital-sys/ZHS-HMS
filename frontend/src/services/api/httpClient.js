import axios from 'axios';
import { env } from '@/core/config/env';
import { clearAccessToken, getAccessToken, setAccessToken } from '@/services/api/tokenStore';

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
 * and race to rotate the same refresh-token family. */
function _refreshAccessToken() {
  if (!_refreshPromise) {
    _refreshPromise = httpClient
      .post('/auth/refresh')
      .then((data) => {
        setAccessToken(data.data.access_token);
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
      } catch {
        clearAccessToken();
        _onAuthFailure?.();
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
