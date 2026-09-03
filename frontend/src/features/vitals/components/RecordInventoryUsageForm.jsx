'use client';

import { useMemo, useState } from 'react';
import { HeartPulse, Search, Trash2, X } from 'lucide-react';
import { patientsService } from '@/features/patients/api/patientsService';
import {
  useInventoryItems,
  useInventoryPatientContext,
  useRecordInventoryUsage,
} from '@/features/inventory/hooks/useInventory';
import {
  inventoryManualPatientSchema,
  usageLineItemSchema,
} from '@/features/inventory/schemas/inventorySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { SearchSelect } from '@/shared/components/SearchSelect';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { useToast } from '@/shared/components/toast/ToastProvider';
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue';
import { todayDisplayDayKey } from '@/utils/timezone';

/** The "which patient is this for" panel — patient-linked, not
 * visit-linked (a deliberate departure from Pharmacy's own
 * VisitLinkPanel, confirmed design decision — see backend/app/modules/
 * inventory/models.py's InventoryUsageEntry docstring): this module's
 * own ward/emergency population is exactly the group most likely to
 * have no same-day OPD visit at all, so there is no "then pick one of
 * their visits" second step the way MedicineBillingWorkspace.jsx's
 * VisitLinkPanel has — picking a patient is the whole of it. Once
 * picked, their MR number and most recent registered procedure (if any)
 * show as a read-only preview, purely informational — nothing about the
 * usage entry itself depends on a visit existing. Manual Entry mirrors
 * VisitLinkPanel's identical fallback exactly (same three fields, same
 * "all three together" rule, same "no patient/visit record is looked up
 * or created" framing). Fixed for the whole item batch below. */
function PatientLinkPanel({
  mode,
  onModeChange,
  selectedPatient,
  onSelectPatient,
  onClear,
  manualName,
  manualAge,
  manualPhone,
  onManualNameChange,
  onManualAgeChange,
  onManualPhoneChange,
}) {
  const { data: context, isLoading: isLoadingContext } = useInventoryPatientContext(
    selectedPatient?.id,
  );

  if (selectedPatient) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Patient</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-0.5 text-sm">
            <span className="font-medium text-foreground">
              {selectedPatient.full_name} (MR: {selectedPatient.mr_number})
            </span>
            <span className="text-muted-foreground">
              {isLoadingContext
                ? 'Loading recent visit…'
                : context?.latest_visit
                  ? `Most recent visit: ${context.latest_visit.queue_token} · ${context.latest_visit.procedure}`
                  : 'No registered visit on file for this patient.'}
            </span>
          </div>
          <Button type="button" size="sm" variant="outline" onClick={onClear}>
            <X className="h-4 w-4" />
            Change
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Patient</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant={mode === 'search' ? 'default' : 'outline'}
            onClick={() => onModeChange('search')}
          >
            Search & Link Patient
          </Button>
          <Button
            type="button"
            size="sm"
            variant={mode === 'manual' ? 'default' : 'outline'}
            onClick={() => onModeChange('manual')}
          >
            Manual Entry
          </Button>
        </div>

        {mode === 'manual' ? (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap">
              <div className="flex flex-1 flex-col gap-1.5 sm:min-w-[12rem]">
                <Label htmlFor="usage_manual_patient_name">Name</Label>
                <Input
                  id="usage_manual_patient_name"
                  value={manualName}
                  onChange={(event) => onManualNameChange(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="usage_manual_patient_age">Age</Label>
                <Input
                  id="usage_manual_patient_age"
                  type="number"
                  min="0"
                  max="150"
                  className="w-24"
                  value={manualAge}
                  onChange={(event) => onManualAgeChange(event.target.value)}
                />
              </div>
              <div className="flex flex-1 flex-col gap-1.5 sm:min-w-[10rem]">
                <Label htmlFor="usage_manual_patient_phone">Contact Number</Label>
                <Input
                  id="usage_manual_patient_phone"
                  value={manualPhone}
                  onChange={(event) => onManualPhoneChange(event.target.value)}
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              All three fields are required together — for a patient not yet in the system. No
              patient record is looked up or created.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5 sm:max-w-sm">
            <Label>Patient</Label>
            <SearchSelect
              queryKey={['patients', 'search']}
              queryFn={(term) => patientsService.search(term).then((res) => res.data)}
              getLabel={(patient) => patient.full_name}
              getDescription={(patient) => `MR: ${patient.mr_number}`}
              placeholder="Search by name, MR number, phone, or CNIC"
              onSelect={(patient) => onSelectPatient(patient)}
            />
            <p className="text-xs text-muted-foreground">
              Not in the system yet? Switch to Manual Entry above.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** One row's parsed quantity, or an error string. A blank quantity
 * means "this item isn't part of the batch" — never an error. */
function parseLineQuantity(rawQuantity, available) {
  const parsed = usageLineItemSchema.safeParse({ quantity: rawQuantity, reason_note: '' });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? 'Invalid quantity' };
  }
  if (parsed.data.quantity > Number(available)) {
    return { error: `Only ${available} available` };
  }
  return { quantity: parsed.data.quantity };
}

/** Records one-or-more Emergency Stock usage entries against a fixed
 * patient context — the only way emergency_stock_level decreases (see
 * backend/app/modules/inventory/service.py's record_usage docstring).
 *
 * Multi-select checklist shape (2026-09 redesign of the earlier
 * search-one-item-then-Add flow): once a patient is chosen, the whole
 * available Emergency Stock catalogue is shown as one filterable table,
 * each row carrying its own quantity + optional reason input. Any row
 * with a quantity is part of the batch; a compact "Items to Record"
 * list below restates the selection with a remove (X) per row so a
 * mistakenly-added item can be dropped before submitting. One "Record
 * Usage" button POSTs the whole selection to `POST /inventory/usage`,
 * which still writes one fully independent, individually-audited
 * `InventoryUsageEntry` row per item inside a single atomic transaction
 * (all rows commit together, or none do) — see RecordUsageRequest's own
 * backend docstring. No batch/session parent entity is introduced. */
export function RecordInventoryUsageForm() {
  const { toast } = useToast();
  const recordUsage = useRecordInventoryUsage();
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();

  const [linkMode, setLinkMode] = useState('search');
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [manualName, setManualName] = useState('');
  const [manualAge, setManualAge] = useState('');
  const [manualPhone, setManualPhone] = useState('');
  const [usedOn, setUsedOn] = useState(todayDisplayDayKey());

  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearch = useDebouncedValue(searchTerm, 200);
  // `{ [itemId]: { quantity: string, reason: string } }` — a key is
  // present iff the user has touched that row; a row counts toward the
  // batch only once its quantity parses to a positive number.
  const [selections, setSelections] = useState({});

  const [submitError, setSubmitError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const availableItems = useMemo(
    () => (items ?? []).filter((item) => item.is_active && Number(item.emergency_stock_level) > 0),
    [items],
  );

  const visibleItems = useMemo(() => {
    const term = debouncedSearch.trim().toLowerCase();
    if (!term) return availableItems;
    return availableItems.filter((item) => item.name.toLowerCase().includes(term));
  }, [availableItems, debouncedSearch]);

  // Every touched row, resolved back to its catalogue item — drives the
  // "Items to Record" recap list, independent of the search filter so a
  // selected item never vanishes just because it's filtered out above.
  const selectedRows = useMemo(() => {
    return Object.entries(selections)
      .map(([itemId, draft]) => {
        const item = availableItems.find((candidate) => candidate.id === itemId);
        if (!item) return null;
        return { item, quantity: draft.quantity ?? '', reason: draft.reason ?? '' };
      })
      .filter(Boolean);
  }, [selections, availableItems]);

  function setRowQuantity(itemId, quantity) {
    setSelections((current) => {
      const next = { ...current };
      const existing = next[itemId] ?? { quantity: '', reason: '' };
      if (quantity === '' && !existing.reason) {
        delete next[itemId];
      } else {
        next[itemId] = { ...existing, quantity };
      }
      return next;
    });
  }

  function setRowReason(itemId, reason) {
    setSelections((current) => {
      const existing = current[itemId] ?? { quantity: '', reason: '' };
      return { ...current, [itemId]: { ...existing, reason } };
    });
  }

  function removeRow(itemId) {
    setSelections((current) => {
      const next = { ...current };
      delete next[itemId];
      return next;
    });
  }

  function clearPatientLink() {
    setSelectedPatient(null);
    setManualName('');
    setManualAge('');
    setManualPhone('');
  }

  async function handleSubmit() {
    setSubmitError(null);
    setSuccessMessage(null);

    const activeRows = selectedRows.filter((row) => String(row.quantity).trim() !== '');
    if (activeRows.length === 0) {
      setSubmitError('Enter a quantity for at least one item before recording usage.');
      return;
    }

    const parsedLines = [];
    for (const row of activeRows) {
      const result = parseLineQuantity(row.quantity, row.item.emergency_stock_level);
      if (result.error) {
        setSubmitError(`${row.item.name}: ${result.error}`);
        return;
      }
      parsedLines.push({
        item_id: row.item.id,
        quantity: result.quantity,
        reason_note: row.reason.trim() || null,
      });
    }

    let manualPatientPayload = {};
    if (!selectedPatient && linkMode === 'manual') {
      const parsed = inventoryManualPatientSchema.safeParse({
        manual_patient_name: manualName,
        manual_patient_age: manualAge,
        manual_patient_phone: manualPhone,
      });
      if (!parsed.success) {
        setSubmitError('Enter all three manual patient fields, or search for an existing patient.');
        return;
      }
      manualPatientPayload = parsed.data;
    } else if (!selectedPatient) {
      setSubmitError('Select a patient, or switch to Manual Entry.');
      return;
    }

    setIsSubmitting(true);
    try {
      await recordUsage.mutateAsync({
        items: parsedLines,
        used_on: usedOn,
        patient_id: selectedPatient?.id ?? null,
        ...manualPatientPayload,
      });
      const message =
        parsedLines.length === 1
          ? 'Usage entry recorded.'
          : `${parsedLines.length} usage entries recorded.`;
      setSuccessMessage(message);
      toast.success({ title: 'Usage recorded', description: message });
      setSelections({});
      setSearchTerm('');
      clearPatientLink();
    } catch (submitErr) {
      const message = submitErr.message || 'Unable to record this usage batch.';
      setSubmitError(message);
      toast.error({ title: 'Unable to record usage', description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PatientLinkPanel
        mode={linkMode}
        onModeChange={setLinkMode}
        selectedPatient={selectedPatient}
        onSelectPatient={setSelectedPatient}
        onClear={clearPatientLink}
        manualName={manualName}
        manualAge={manualAge}
        manualPhone={manualPhone}
        onManualNameChange={setManualName}
        onManualAgeChange={setManualAge}
        onManualPhoneChange={setManualPhone}
      />

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle>Select Items</CardTitle>
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="Search item by name…"
                className="pl-8"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {isLoading ? (
            <PageLoader label="Loading Emergency Stock items" />
          ) : isError ? (
            <PageError
              error={error}
              reset={refetch}
              message="Couldn't load Emergency Stock items."
            />
          ) : availableItems.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No active items currently have Emergency Stock available.
            </p>
          ) : visibleItems.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No items match &quot;{debouncedSearch}&quot;.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Available</TableHead>
                  <TableHead className="w-32">Quantity</TableHead>
                  <TableHead>Reason (optional)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleItems.map((item) => {
                  const draft = selections[item.id];
                  const isSelected = Boolean(draft && String(draft.quantity).trim() !== '');
                  return (
                    <TableRow key={item.id} className={isSelected ? 'bg-muted/40' : undefined}>
                      <TableCell className="font-medium text-foreground">
                        {item.name} <span className="text-muted-foreground">({item.unit})</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {item.emergency_stock_level}
                      </TableCell>
                      <TableCell>
                        <Input
                          type="number"
                          step="0.01"
                          min="0"
                          aria-label={`Quantity for ${item.name}`}
                          className="w-28"
                          value={draft?.quantity ?? ''}
                          onChange={(event) => setRowQuantity(item.id, event.target.value)}
                        />
                      </TableCell>
                      <TableCell>
                        <Input
                          aria-label={`Reason for ${item.name}`}
                          value={draft?.reason ?? ''}
                          onChange={(event) => setRowReason(item.id, event.target.value)}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          <div className="flex flex-col gap-1.5 sm:max-w-xs">
            <Label htmlFor="usage_used_on">Used On</Label>
            <Input
              id="usage_used_on"
              type="date"
              value={usedOn}
              onChange={(event) => setUsedOn(event.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Items to Record</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {selectedRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No items selected yet — enter a quantity against an item above.
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Item</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {selectedRows.map((row) => (
                    <TableRow key={row.item.id}>
                      <TableCell className="font-medium text-foreground">
                        {row.item.name}{' '}
                        <span className="text-muted-foreground">({row.item.unit})</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {String(row.quantity).trim() === '' ? '—' : row.quantity}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{row.reason || '—'}</TableCell>
                      <TableCell>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          aria-label={`Remove ${row.item.name}`}
                          onClick={() => removeRow(row.item.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div>
                <Button type="button" onClick={handleSubmit} disabled={isSubmitting}>
                  <HeartPulse className="h-4 w-4" />
                  {isSubmitting ? 'Recording…' : 'Record Usage'}
                </Button>
              </div>
            </>
          )}
          {submitError ? (
            <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {submitError}
            </p>
          ) : null}
          {successMessage ? (
            <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              {successMessage}
            </p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
