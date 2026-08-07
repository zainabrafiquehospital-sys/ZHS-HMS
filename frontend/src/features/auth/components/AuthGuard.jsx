'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { ROUTES } from '@/core/constants/routes';
import { PageLoader } from '@/shared/components/PageLoader';

/**
 * Wraps every route under the `(dashboard)` group. The actual security
 * boundary is always the backend's RBAC (every request carries the
 * bearer token and is independently authorized there) — this guard only
 * prevents an unauthenticated browser from flashing protected UI before
 * redirecting, it is not itself a trust boundary.
 */
export function AuthGuard({ children }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace(ROUTES.LOGIN);
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading) {
    return <PageLoader label="Checking your session" />;
  }
  if (!isAuthenticated) {
    return null;
  }
  return children;
}
