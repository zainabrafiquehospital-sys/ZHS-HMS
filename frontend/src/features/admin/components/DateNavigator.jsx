'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { formatDisplayDate, shiftDisplayDayKey, todayDisplayDayKey } from '@/utils/timezone';

/** Prev/next-day + date-picker control, capped at today — originally
 * built for Admin Overview's "Visit Activity" card, extracted here so
 * the Leads section (features/admin/components/LeadsSection.jsx) can
 * reuse the exact same control/behavior rather than a second
 * hand-rolled date picker with its own subtly different edge cases. */
export function DateNavigator({ selectedDate, onChange }) {
  const today = todayDisplayDayKey();
  const isToday = selectedDate === today;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        onClick={() => onChange(shiftDisplayDayKey(selectedDate, -1))}
        aria-label="Previous day"
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <Input
        type="date"
        value={selectedDate}
        max={today}
        onChange={(event) => event.target.value && onChange(event.target.value)}
        className="w-auto"
      />
      <Button
        size="sm"
        variant="outline"
        disabled={isToday}
        onClick={() => onChange(shiftDisplayDayKey(selectedDate, 1))}
        aria-label="Next day"
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
      {!isToday ? (
        <Button size="sm" variant="ghost" onClick={() => onChange(today)}>
          Today
        </Button>
      ) : null}
      <span className="text-sm text-muted-foreground">{formatDisplayDate(selectedDate)}</span>
    </div>
  );
}
