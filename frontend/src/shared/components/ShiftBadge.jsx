'use client';

import { useEffect, useState } from 'react';
import { Sun, Moon } from 'lucide-react';
import { Badge } from '@/shared/components/ui/Badge';
import { getCurrentShift } from '@/utils/timezone';

const SHIFT_ICON = { morning: Sun, night: Moon };
const SHIFT_LABEL = { morning: 'Morning Shift', night: 'Night Shift' };

/** "Which shift is live right now" indicator, in DISPLAY_TIMEZONE (see
 * utils/timezone.js's `getCurrentShift`) — shared by every shift-based
 * worklist (Reception, Vitals) rather than each screen computing/
 * displaying it independently. Re-checks every minute so it flips over
 * on its own at the actual shift boundary without a page reload,
 * without needing a much shorter (wasteful) interval. */
export function ShiftBadge() {
  const [shift, setShift] = useState(getCurrentShift);

  useEffect(() => {
    const id = setInterval(() => setShift(getCurrentShift()), 60_000);
    return () => clearInterval(id);
  }, []);

  const Icon = SHIFT_ICON[shift];
  return (
    <Badge variant="outline" className="gap-1">
      <Icon className="h-3.5 w-3.5" />
      {SHIFT_LABEL[shift]}
    </Badge>
  );
}
