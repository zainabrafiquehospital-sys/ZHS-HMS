'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { resolveLandingRoute } from '@/core/constants/access';
import { PageLoader } from '@/shared/components/PageLoader';

/**
 * Wraps a module's page content — blocks direct navigation to a route
 * the signed-in user has no permission for (not just hiding the
 * sidebar link to it), redirecting to their own landing module instead
 * of a dead end. Same caveat as AuthGuard: the backend's own
 * `require_permission()` on every request is the actual authorization
 * boundary (see app/modules/auth/dependencies.py) — this only prevents
 * a browser from flashing/rendering UI the user has no business seeing.
 */
export function RequirePermission({ permission, children }) {
  const { hasPermission, permissions, isLoading } = useAuth();
  const router = useRouter();
  const allowed = hasPermission(permission);

  useEffect(() => {
    if (!isLoading && !allowed) {
      router.replace(resolveLandingRoute(permissions));
    }
  }, [isLoading, allowed, permissions, router]);

  if (isLoading) {
    return <PageLoader label="Checking access" />;
  }
  if (!allowed) {
    return null;
  }
  return children;
}
