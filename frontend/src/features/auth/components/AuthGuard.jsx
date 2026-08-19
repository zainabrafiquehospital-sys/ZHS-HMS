'use client';

import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { ROUTES } from '@/core/constants/routes';
import { PageLoader } from '@/shared/components/PageLoader';

/**
 * Wraps every route under the `(dashboard)` group. The actual security
 * boundary is always the backend's RBAC (every request carries the
 * bearer token and is independently authorized there) — this guard only
 * prevents an unauthenticated browser from flashing protected UI before
 * redirecting, it is not itself a trust boundary.
 *
 * Also traps a signed-in user whose `must_change_password` flag is set
 * (2026-08-19 audit fix pass) on `/change-password` until they've
 * actually changed it — every permission-gated endpoint already 403s
 * them regardless (`PASSWORD_CHANGE_REQUIRED`, see backend/app/modules/
 * auth/dependencies.py's `require_permission`), so this is purely a UX
 * improvement (no protected page's data-fetching hooks even get a
 * chance to run and fail) over letting them wander into a dead end.
 * Re-runs on every navigation (`pathname` in the effect's dependency
 * list), so attempting to navigate away from /change-password while the
 * flag is still set bounces straight back — this is what makes it a
 * trap, not a one-time redirect.
 */
export function AuthGuard({ children }) {
  const { isAuthenticated, isLoading, user } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const mustChangePassword = Boolean(user?.must_change_password);

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      router.replace(ROUTES.LOGIN);
      return;
    }
    if (mustChangePassword && pathname !== ROUTES.CHANGE_PASSWORD) {
      router.replace(ROUTES.CHANGE_PASSWORD);
    }
  }, [isLoading, isAuthenticated, mustChangePassword, pathname, router]);

  if (isLoading) {
    return <PageLoader label="Checking your session" />;
  }
  if (!isAuthenticated) {
    return null;
  }
  if (mustChangePassword && pathname !== ROUTES.CHANGE_PASSWORD) {
    return null;
  }
  return children;
}
