'use client';

import { PageError } from '@/shared/components/PageError';

export default function DashboardError({ error, reset }) {
  return <PageError error={error} reset={reset} />;
}
