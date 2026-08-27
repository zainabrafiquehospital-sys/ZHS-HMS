'use client';

import { useState } from 'react';
import { HeartPulse, Plus, Trash2, X } from 'lucide-react';
import { patientsService } from '@/features/patients/api/patientsService';
import { inventoryService } from '@/features/inventory/api/inventoryService';
import {
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { todayDisplayDayKey } from '@/utils/timezone';

let nextLineKey = 0;

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
 * or created" framing). Fixed for the whole item batch below — the same
 * "one context, items added one at a time" shape RegisterVisitForm.jsx
 * uses for its own patient/visit context while procedures are added. */
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

/** Records one-or-more Emergency Stock usage entries against a fixed
 * patient context — the only way emergency_stock_level decreases (see
 * backend/app/modules/inventory/service.py's record_usage docstring).
 *
 * Add-to-a-running-list-then-submit-once shape (2026-08-27 redesign),
 * matching ProcedureItemsEditor.jsx (Reception) and
 * MedicineBillingWorkspace.jsx's (Pharmacy) own item-adding pattern:
 * pick an item + quantity (+ optional per-line reason note), add it to
 * the visible list, repeat, then one "Record Usage" submit sends the
 * whole list together. The backend still writes one fully independent
 * InventoryUsageEntry row per line (no batch/session entity), just
 * atomically — see RecordUsageRequest's own docstring. Item picker is a
 * SearchSelect against the active-items-only `/inventory/items/search`
 * endpoint, same reuse as Receive Stock/Transfer to Emergency. */
export function RecordInventoryUsageForm() {
  const recordUsage = useRecordInventoryUsage();
  const [linkMode, setLinkMode] = useState('search');
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [manualName, setManualName] = useState('');
  const [manualAge, setManualAge] = useState('');
  const [manualPhone, setManualPhone] = useState('');
  const [usedOn, setUsedOn] = useState(todayDisplayDayKey());

  const [selectedItem, setSelectedItem] = useState(null);
  const [quantity, setQuantity] = useState('');
  const [reasonNote, setReasonNote] = useState('');
  const [lineError, setLineError] = useState(null);
  const [lines, setLines] = useState([]);

  const [submitError, setSubmitError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function clearPatientLink() {
    setSelectedPatient(null);
    setManualName('');
    setManualAge('');
    setManualPhone('');
  }

  function handleAddLine() {
    setLineError(null);
    if (!selectedItem) return;
    const parsed = usageLineItemSchema.safeParse({ quantity, reason_note: reasonNote });
    if (!parsed.success) {
      setLineError(parsed.error.issues[0]?.message ?? 'Invalid quantity');
      return;
    }

    setLines((current) => [
      ...current,
      {
        key: nextLineKey++,
        item_id: selectedItem.id,
        name: selectedItem.name,
        unit: selectedItem.unit,
        available: selectedItem.emergency_stock_level,
        quantity: parsed.data.quantity,
        reason_note: parsed.data.reason_note || '',
      },
    ]);
    setSelectedItem(null);
    setQuantity('');
    setReasonNote('');
  }

  function handleRemoveLine(key) {
    setLines((current) => current.filter((line) => line.key !== key));
  }

  async function handleSubmitBatch() {
    setSubmitError(null);
    setSuccessMessage(null);

    if (lines.length === 0) {
      setSubmitError('Add at least one item before recording usage.');
      return;
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
        items: lines.map((line) => ({
          item_id: line.item_id,
          quantity: line.quantity,
          reason_note: line.reason_note || null,
        })),
        used_on: usedOn,
        patient_id: selectedPatient?.id ?? null,
        ...manualPatientPayload,
      });
      setSuccessMessage(
        lines.length === 1 ? 'Usage entry recorded.' : `${lines.length} usage entries recorded.`,
      );
      setLines([]);
      clearPatientLink();
    } catch (submitErr) {
      setSubmitError(submitErr.message || 'Unable to record this usage batch.');
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
          <CardTitle>Add Item</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end">
            <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
              <Label>Item</Label>
              <SearchSelect
                queryKey={['inventory', 'items', 'search']}
                queryFn={(term) => inventoryService.searchItems(term).then((res) => res.data)}
                getLabel={(item) => item.name}
                getDescription={(item) =>
                  `${item.unit} — ${item.emergency_stock_level} available`
                }
                placeholder="Search item by name"
                selectedLabel={selectedItem ? selectedItem.name : ''}
                onSelect={(item) => setSelectedItem(item)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="usage_quantity">Quantity</Label>
              <Input
                id="usage_quantity"
                type="number"
                step="0.01"
                min="0"
                className="w-28"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
              />
            </div>
            <div className="flex min-w-[200px] flex-1 flex-col gap-1.5">
              <Label htmlFor="usage_line_reason_note">Reason (optional)</Label>
              <Input
                id="usage_line_reason_note"
                value={reasonNote}
                onChange={(event) => setReasonNote(event.target.value)}
              />
            </div>
            <Button type="button" onClick={handleAddLine} disabled={!selectedItem}>
              <Plus className="h-4 w-4" />
              Add Item
            </Button>
          </div>
          {lineError ? <p className="text-xs text-destructive">{lineError}</p> : null}
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
          {lines.length === 0 ? (
            <p className="text-sm text-muted-foreground">No items added yet.</p>
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
                  {lines.map((line) => (
                    <TableRow key={line.key}>
                      <TableCell className="font-medium text-foreground">
                        {line.name} <span className="text-muted-foreground">({line.unit})</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{line.quantity}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {line.reason_note || '—'}
                      </TableCell>
                      <TableCell>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() => handleRemoveLine(line.key)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div>
                <Button type="button" onClick={handleSubmitBatch} disabled={isSubmitting}>
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
