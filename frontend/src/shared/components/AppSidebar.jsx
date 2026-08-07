'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayoutDashboard, ClipboardList, Stethoscope, HeartPulse, Receipt } from 'lucide-react';
import { cn } from '@/utils/cn';
import { ROUTES } from '@/core/constants/routes';
import { useAuth } from '@/features/auth/hooks/useAuth';

const NAV_ITEMS = [
  { href: ROUTES.DASHBOARD, label: 'Dashboard', icon: LayoutDashboard, permission: null },
  {
    href: ROUTES.RECEPTION,
    label: 'Reception',
    icon: ClipboardList,
    permission: 'reception:register_visit',
  },
  {
    href: ROUTES.DOCTOR_QUEUE,
    label: 'Doctor Queue',
    icon: Stethoscope,
    permission: 'consultation:start',
  },
  { href: ROUTES.VITALS, label: 'Vitals', icon: HeartPulse, permission: 'vitals:read' },
  { href: ROUTES.BILLING, label: 'Billing', icon: Receipt, permission: 'billing:read' },
];

export function AppSidebar() {
  const pathname = usePathname();
  const { hasPermission } = useAuth();
  // Unauthorized modules are removed from the DOM entirely, not just
  // disabled/greyed out — a user must never see a link to a screen
  // they aren't permitted to open (Phase 6 fast-registration §1).
  const visibleItems = NAV_ITEMS.filter(
    (item) => item.permission === null || hasPermission(item.permission),
  );

  return (
    <nav className="flex h-full flex-col gap-1 p-3">
      <div className="mb-2 px-2 py-2 text-sm font-semibold text-foreground">Gynecology HMS</div>
      {visibleItems.map(({ href, label, icon: Icon }) => {
        const isActive = href === '/' ? pathname === href : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
              isActive
                ? 'bg-secondary text-secondary-foreground'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
