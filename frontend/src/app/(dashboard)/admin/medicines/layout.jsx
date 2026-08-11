import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function AdminMedicinesLayout({ children }) {
  return <RequirePermission permission="pharmacy:manage">{children}</RequirePermission>;
}
