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

  changePassword({ currentPassword, newPassword }) {
    return httpClient.post('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    });
  },

  // Self-service signup (Receptionist or Vitals staff — see backend/
  // app/modules/auth/signup_schemas.py's SignupRole) — email/OTP/
  // approval flow, same for both roles.
  signup({ fullName, email, phoneNumber, password, shift, role }) {
    return httpClient.post('/auth/signup', {
      full_name: fullName,
      email,
      phone_number: phoneNumber,
      password,
      shift,
      role,
    });
  },

  verifyEmail({ email, code }) {
    return httpClient.post('/auth/verify-email', { email, code });
  },

  resendSignupOtp({ email }) {
    return httpClient.post('/auth/resend-otp', { email });
  },

  forgotPassword({ email }) {
    return httpClient.post('/auth/forgot-password', { email });
  },

  verifyResetOtp({ email, code }) {
    return httpClient.post('/auth/verify-reset-otp', { email, code });
  },

  resetPassword({ email, code, newPassword }) {
    return httpClient.post('/auth/reset-password', {
      email,
      code,
      new_password: newPassword,
    });
  },
};
