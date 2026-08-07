'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { authService } from '@/features/auth/api/authService';
import { clearAccessToken, setAccessToken } from '@/services/api/tokenStore';
import { setOnAuthFailure } from '@/services/api/httpClient';
import { ROUTES } from '@/core/constants/routes';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  const clearSession = useCallback(() => {
    clearAccessToken();
    setUser(null);
  }, []);

  const logout = useCallback(async () => {
    try {
      await authService.logout();
    } finally {
      clearSession();
      router.push(ROUTES.LOGIN);
    }
  }, [clearSession, router]);

  useEffect(() => {
    // Registered once — httpClient calls this if a refresh-on-401 ever
    // definitively fails during normal use (e.g. the refresh cookie
    // itself expired mid-session), so a stale session never lingers in
    // the UI showing data the backend no longer accepts requests for.
    setOnAuthFailure(() => {
      clearSession();
      router.push(ROUTES.LOGIN);
    });
  }, [clearSession, router]);

  useEffect(() => {
    // Silent refresh on load: a hard page reload loses the in-memory
    // access token (see tokenStore.js's module docstring for why that's
    // deliberate) but the httpOnly refresh cookie survives — this
    // exchanges it for a fresh access token without asking the user to
    // log in again, exactly like any refresh-cookie-based session.
    let cancelled = false;
    authService
      .refresh()
      .then((data) => {
        if (cancelled) return;
        setAccessToken(data.data.access_token);
        setUser(data.data.user);
      })
      .catch(() => {
        if (cancelled) return;
        clearAccessToken();
        setUser(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async ({ email, password, rememberMe }) => {
    const data = await authService.login({ email, password, rememberMe });
    setAccessToken(data.data.access_token);
    setUser(data.data.user);
    return data.data.user;
  }, []);

  const hasPermission = useCallback(
    (permissionCode) => Boolean(user?.permissions?.includes(permissionCode)),
    [user],
  );

  const value = {
    user,
    isLoading,
    isAuthenticated: Boolean(user),
    permissions: user?.permissions ?? [],
    hasPermission,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
