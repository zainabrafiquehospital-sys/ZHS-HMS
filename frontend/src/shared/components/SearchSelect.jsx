'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2, Search } from 'lucide-react';
import { Input } from '@/shared/components/ui/Input';
import { cn } from '@/utils/cn';
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue';

/**
 * A minimal debounced search-and-pick control — not a full combobox
 * library. Sufficient for this build's lookups (patient, doctor): type
 * to search, click a result to select it. Reused across features rather
 * than each one re-implementing the same debounce + dropdown logic.
 */
export function SearchSelect({
  queryKey,
  queryFn,
  getLabel,
  getDescription,
  onSelect,
  placeholder = 'Search…',
  minChars = 2,
  selectedLabel,
}) {
  const [term, setTerm] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const debouncedTerm = useDebouncedValue(term, 300);

  const { data, isFetching } = useQuery({
    queryKey: [...queryKey, debouncedTerm],
    queryFn: () => queryFn(debouncedTerm),
    enabled: debouncedTerm.length >= minChars,
  });

  const results = data ?? [];

  return (
    <div className="relative">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={term}
          onChange={(event) => {
            setTerm(event.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          placeholder={selectedLabel || placeholder}
          className="pl-8"
        />
        {isFetching ? (
          <Loader2 className="absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
        ) : null}
      </div>
      {isOpen && debouncedTerm.length >= minChars ? (
        <div className="absolute z-10 mt-1 w-full rounded-md border border-border bg-card shadow-md">
          {results.length === 0 && !isFetching ? (
            <p className="px-3 py-2 text-sm text-muted-foreground">No matches</p>
          ) : (
            <ul className="max-h-56 overflow-y-auto py-1">
              {results.map((item) => (
                <li key={getLabel(item)}>
                  <button
                    type="button"
                    className={cn(
                      'flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-muted',
                    )}
                    onClick={() => {
                      onSelect(item);
                      setTerm('');
                      setIsOpen(false);
                    }}
                  >
                    <span className="font-medium text-foreground">{getLabel(item)}</span>
                    {getDescription ? (
                      <span className="text-xs text-muted-foreground">{getDescription(item)}</span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
