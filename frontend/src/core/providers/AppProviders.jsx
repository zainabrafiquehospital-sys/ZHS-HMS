'use client';

import { ThemeProvider } from '@/core/providers/ThemeProvider';
import { QueryProvider } from '@/core/providers/QueryProvider';
import { AuthProvider } from '@/features/auth/hooks/useAuth';
import { ToastProvider } from '@/shared/components/toast/ToastProvider';

export function AppProviders({ children }) {
  return (
    <ThemeProvider>
      <QueryProvider>
        <ToastProvider>
          <AuthProvider>{children}</AuthProvider>
        </ToastProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}
