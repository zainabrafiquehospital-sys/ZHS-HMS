'use client';

import { PageError } from '@/shared/components/PageError';

export default function RootError({ error, reset }) {
  return <PageError error={error} reset={reset} message="The application failed to load." />;
}
