import { DashboardShell } from '@/shared/layouts/DashboardShell';
import { AppSidebar } from '@/shared/components/AppSidebar';
import { AppHeader } from '@/shared/components/AppHeader';
import { AuthGuard } from '@/features/auth/components/AuthGuard';

/**
 * Shared shell for every authenticated/application route.
 */
export default function DashboardLayout({ children }) {
  return (
    <AuthGuard>
      <DashboardShell sidebar={<AppSidebar />} header={<AppHeader />}>
        {children}
      </DashboardShell>
    </AuthGuard>
  );
}
