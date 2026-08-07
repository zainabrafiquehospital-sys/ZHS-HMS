'use client';

import { LogOut } from 'lucide-react';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { Button } from '@/shared/components/ui/Button';

export function AppHeader() {
  const { user, logout } = useAuth();

  return (
    <div className="flex w-full items-center justify-between">
      <div className="text-sm text-muted-foreground">
        {user ? (
          <>
            Signed in as <span className="font-medium text-foreground">{user.full_name}</span>
            {user.roles?.length ? (
              <span className="ml-2 text-xs text-muted-foreground">({user.roles.join(', ')})</span>
            ) : null}
          </>
        ) : null}
      </div>
      <Button variant="ghost" size="sm" onClick={logout}>
        <LogOut className="h-4 w-4" />
        Sign out
      </Button>
    </div>
  );
}
