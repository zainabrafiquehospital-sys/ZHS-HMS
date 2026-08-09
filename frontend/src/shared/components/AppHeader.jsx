'use client';

import { LogOut } from 'lucide-react';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { Button } from '@/shared/components/ui/Button';

function initialsFor(fullName) {
  if (!fullName) return '?';
  const parts = fullName.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (first + last).toUpperCase();
}

/** Same "Signed in as X (role)" content as before — brand visual
 * treatment only (Part 3.3), no new functionality: an initials
 * avatar in the brand navy rather than plain text, and the role tag
 * as a small pill instead of parenthesized text. */
export function AppHeader() {
  const { user, logout } = useAuth();

  return (
    <div className="flex w-full items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2.5">
        {user ? (
          <>
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-navy text-xs font-semibold text-white">
              {initialsFor(user.full_name)}
            </div>
            <div className="flex min-w-0 flex-col leading-tight">
              <span className="truncate text-sm font-medium text-foreground">
                {user.full_name}
              </span>
              {user.roles?.length ? (
                <span className="truncate text-xs text-muted-foreground">
                  {user.roles.join(', ')}
                </span>
              ) : null}
            </div>
          </>
        ) : null}
      </div>
      <Button variant="ghost" size="sm" onClick={logout}>
        <LogOut className="h-4 w-4" />
        <span className="hidden sm:inline">Sign out</span>
      </Button>
    </div>
  );
}
