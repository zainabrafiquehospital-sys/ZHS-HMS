import { httpClient } from '@/services/api/httpClient';

/**
 * Auth is not a CRUD resource, so this does not extend BaseService —
 * each call maps directly to one of the six endpoints
 * backend/app/modules/auth/router.py exposes.
 */
export const authService = {
  login({ email, password, rememberMe }) {
    return httpClient.post('/auth/login', {
      email,
      password,
      remember_me: rememberMe,
    });
  },

  refresh() {
    return httpClient.post('/auth/refresh');
  },

  logout() {
    return httpClient.post('/auth/logout');
  },

  me() {
    return httpClient.get('/auth/me');
  },
};
