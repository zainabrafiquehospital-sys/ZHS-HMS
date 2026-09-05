import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { httpClient, setOnAuthFailure } from '@/services/api/httpClient';
import {
  clearAccessToken,
  clearUserId,
  getAccessToken,
  getUserId,
  setAccessToken,
  setUserId,
} from '@/services/api/tokenStore';

// These tests drive the real `httpClient` instance's real interceptors
// end to end, replacing only the lowest-level axios `adapter` (the
// transport axios itself calls to actually perform a request) with a
// synchronous stand-in — the standard, dependency-free way to test axios
// interceptor logic without a real network call or a mocking library
// this project doesn't already depend on. Each helper below mirrors
// exactly what a real HTTP response/failure looks like to axios:
// `httpError` is a genuine HTTP error response (a `.response` is
// present, e.g. a real 401/403 from the server); `networkError` is what
// a timeout/dropped connection/aborted request looks like (no
// `.response` at all) — the exact distinction this fix's whole bug was
// about conflating.
function jsonResponse(config, status, data) {
  return Promise.resolve({ data, status, statusText: '', headers: {}, config });
}

function httpError(config, status, data) {
  const error = new Error(`Request failed with status code ${status}`);
  error.response = { data, status, statusText: '', headers: {}, config };
  error.config = config;
  return Promise.reject(error);
}

function networkError(config) {
  const error = new Error('timeout of 15000ms exceeded');
  error.code = 'ECONNABORTED';
  error.config = config;
  // Deliberately no `.response` — this is the real shape of a timeout or
  // a request the browser dropped/aborted (e.g. a backgrounded tab's
  // polling hook losing connectivity), never a server-issued rejection.
  return Promise.reject(error);
}

describe('httpClient 401 -> refresh -> retry interceptor', () => {
  const originalAdapter = httpClient.defaults.adapter;
  let onAuthFailure;

  beforeEach(() => {
    setAccessToken('initial-access-token');
    setUserId('user-1');
    onAuthFailure = vi.fn();
    setOnAuthFailure(onAuthFailure);
  });

  afterEach(() => {
    httpClient.defaults.adapter = originalAdapter;
    clearAccessToken();
    clearUserId();
    setOnAuthFailure(null);
  });

  it('clears the session and calls the auth-failure callback when /auth/refresh genuinely answers 401', async () => {
    let protectedCallCount = 0;
    httpClient.defaults.adapter = (config) => {
      if (config.url === '/auth/refresh') {
        return httpError(config, 401, {
          data: null,
          error: { code: 'REFRESH_TOKEN_INVALID', message: 'Refresh token is invalid.', details: null },
        });
      }
      protectedCallCount += 1;
      return httpError(config, 401, {
        data: null,
        error: { code: 'AUTHENTICATION_ERROR', message: 'Authentication required.', details: {} },
      });
    };

    await expect(httpClient.get('/some/protected')).rejects.toMatchObject({
      status: 401,
      // The *original* request's 401 body, not the refresh call's own —
      // preserved unchanged by this fix (see the interceptor's own
      // "fall through ... using the original 401" comment).
      code: 'AUTHENTICATION_ERROR',
    });

    expect(onAuthFailure).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
    expect(getUserId()).toBeNull();
    // Never retried — a failed refresh means the interceptor falls
    // through immediately, it does not re-attempt the original request.
    expect(protectedCallCount).toBe(1);
  });

  it('does NOT clear the session or call the auth-failure callback when /auth/refresh fails with a network error, and the original request still rejects normally', async () => {
    let protectedCallCount = 0;
    httpClient.defaults.adapter = (config) => {
      if (config.url === '/auth/refresh') {
        return networkError(config);
      }
      protectedCallCount += 1;
      return httpError(config, 401, {
        data: null,
        error: { code: 'AUTHENTICATION_ERROR', message: 'Authentication required.', details: {} },
      });
    };

    await expect(httpClient.get('/some/protected')).rejects.toMatchObject({
      status: 401,
      code: 'AUTHENTICATION_ERROR',
    });

    // The whole point of the fix: a transient failure of the refresh
    // call itself must never be treated as "the session is invalid".
    expect(onAuthFailure).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe('initial-access-token');
    expect(getUserId()).toBe('user-1');
    expect(protectedCallCount).toBe(1);
  });

  it('still transparently retries the original request with the new token when refresh succeeds (unchanged happy path)', async () => {
    let protectedCallCount = 0;
    httpClient.defaults.adapter = (config) => {
      if (config.url === '/auth/refresh') {
        return jsonResponse(config, 200, {
          data: { access_token: 'fresh-access-token', user: { id: 'user-1' } },
          meta: null,
          error: null,
        });
      }
      protectedCallCount += 1;
      if (protectedCallCount === 1) {
        return httpError(config, 401, {
          data: null,
          error: { code: 'AUTHENTICATION_ERROR', message: 'Authentication required.', details: {} },
        });
      }
      // The retry — must carry the freshly refreshed token.
      expect(config.headers.Authorization).toBe('Bearer fresh-access-token');
      return jsonResponse(config, 200, { data: { ok: true }, meta: null, error: null });
    };

    await expect(httpClient.get('/some/protected')).resolves.toMatchObject({
      data: { ok: true },
    });

    expect(onAuthFailure).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe('fresh-access-token');
    expect(getUserId()).toBe('user-1');
    expect(protectedCallCount).toBe(2);
  });
});
