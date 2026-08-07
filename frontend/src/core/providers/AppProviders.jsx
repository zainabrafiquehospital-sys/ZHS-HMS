'use client';

import { ThemeProvider } from '@/core/providers/ThemeProvider';
import { QueryProvider } from '@/core/providers/QueryProvider';
import { AuthProvider } from '@/features/auth/hooks/useAuth';

export function AppProviders({ children }) {
  return (
    <ThemeProvider>
      <QueryProvider>
        <AuthProvider>{children}</AuthProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}
