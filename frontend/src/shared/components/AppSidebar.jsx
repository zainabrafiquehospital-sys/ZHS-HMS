'use client';

import Image from 'next/image';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  ClipboardList,
  Stethoscope,
  HeartPulse,
  Receipt,
  ShieldCheck,
  Pill,
  PackageSearch,
  BookUser,
  Users,
  ListChecks,
  Warehouse,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { ROUTES } from '@/core/constants/routes';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { env } from '@/core/config/env';

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
  { href: ROUTES.PHARMACY, label: 'Pharmacy', icon: Pill, permission: 'pharmacy:bill' },
  // Inventory Manager-only — gated on inventory:manage, not the
  // broader inventory:read Vitals also holds (see access.js's identical
  // MODULE_ACCESS entry's own comment): Vitals' own usage/restock
  // actions live on their own worklist screen, not this one.
  {
    href: ROUTES.INVENTORY,
    label: 'Inventory',
    icon: Warehouse,
    permission: 'inventory:manage',
  },
  // A genuinely shared screen, not an Admin sub-screen — gated purely on
  // `patients:read`, which both Admin (full catalog) and Receptionist
  // (granted directly — see scripts/seed_launch_bootstrap.py's
  // RECEPTIONIST_PERMISSION_CODES) hold. Its route lives at the
  // top-level /patients, not nested under /admin, specifically so
  // Admin's own stricter `users:read` parent gate never blocks a
  // Receptionist from reaching it (see app/(dashboard)/patients/
  // layout.jsx's docstring).
  {
    href: ROUTES.PATIENTS,
    label: 'Patient Directory',
    icon: BookUser,
    permission: 'patients:read',
  },
  // Gated on users:read, not a module-specific permission — see
  // core/constants/access.js's identical MODULE_ACCESS entry for why
  // that code specifically (only the admin role holds it).
  { href: ROUTES.ADMIN, label: 'Admin', icon: ShieldCheck, permission: 'users:read' },
  // Its own top-level entry rather than nested Admin sub-navigation —
  // there is no existing "sub-nav within Admin" pattern in this codebase
  // (Admin itself is a single flat page; see features/admin/), so this
  // mirrors how Admin's own link works: gated purely on a permission
  // (pharmacy:manage) only the admin role is ever granted (see
  // scripts/seed_launch_bootstrap.py), not on the URL being under /admin.
  {
    href: ROUTES.ADMIN_MEDICINES,
    label: 'Medicines',
    icon: PackageSearch,
    permission: 'pharmacy:manage',
  },
  // Same "own top-level entry, permission-gated only" shape as Medicines
  // above — an Admin sub-screen, not a landing module (see access.js's
  // MODULE_ACCESS, which deliberately omits it for the same reason,
  // 2026-08-21 addition).
  {
    href: ROUTES.ADMIN_PROCEDURES,
    label: 'Procedures',
    icon: ListChecks,
    permission: 'procedures:manage',
  },
  // Same "own top-level entry, permission-gated only" shape as Medicines
  // above — an Admin sub-screen, not a landing module (see access.js's
  // MODULE_ACCESS, which deliberately omits it for the same reason),
  // gated on the same read permission its own route's layout.jsx
  // already enforces server-side.
  {
    href: ROUTES.ADMIN_EMPLOYEES,
    label: 'Employee Accounts',
    icon: Users,
    permission: 'users:read',
  },
];

/**
 * Navy brand sidebar (Part 3.1). The logo sits in its own small white
 * "chip" rather than directly on the navy fill — see this codebase's
 * own investigation notes on logo.png: it's a mixed-contrast asset
 * (dark-navy "zainab" text alongside white/silver "RAFIQ" + Arabic
 * calligraphy), so no single background lets every element of the
 * source image read at full contrast. A light chip keeps the logo on
 * the light background it was actually designed for, regardless of
 * the surrounding chrome color — the standard fix for this exact
 * situation, not a re-edit of the logo asset itself.
 */
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
    <nav className="flex h-full flex-col gap-1 bg-brand-navy p-3 text-white">
      <div className="mb-4 flex items-center gap-2.5 px-1 py-2">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-white p-1 shadow-sm">
          <Image src="/images/logo.png" alt={env.appName} width={40} height={40} priority />
        </div>
        <div className="min-w-0 text-sm font-semibold leading-tight text-white">{env.appName}</div>
      </div>
      {visibleItems.map(({ href, label, icon: Icon }) => {
        const isActive = href === '/' ? pathname === href : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              'flex items-center gap-2 rounded-md px-3 py-2.5 text-sm font-medium transition-colors',
              isActive
                ? 'bg-white text-brand-navy shadow-sm'
                : 'text-white/75 hover:bg-white/10 hover:text-white',
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
