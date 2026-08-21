'use client';

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { proceduresService } from '@/features/visits/api/proceduresService';
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

function money(amount) {
  return `Rs. ${Number(amount).toFixed(2)}`;
}

let _nextKey = 0;
function nextItemKey() {
  _nextKey += 1;
  return `procedure-item-${_nextKey}`;
}

/** Shared procedure line-item editor for a Visit (2026-08-21 addition)
 * — used by both RegisterVisitForm (starts empty) and AdminOverview's
 * itemized EditVisitDialog (pre-filled from the visit's existing
 * `procedure_items`, replaced wholesale on submit) — one UI for
 * building a procedure-item list, not two.
 *
 * Mirrors MedicineBillingWorkspace.jsx's "search the catalog, add a
 * line item, running total below" UX pattern as literally as makes
 * sense: a catalog-selected procedure's price is LOCKED (confirmed
 * design decision, mirroring Medicine's own price-integrity rule — the
 * Amount shown is read-only, never a text input, for a catalog row).
 * A parallel "type it in directly" fallback coexists alongside the
 * catalog search — never blocking work on a procedure the admin hasn't
 * added to the catalog yet — and both kinds of row can sit in the same
 * list, each independently either catalog-linked or manual (see
 * backend/app/modules/visits/models.py's `VisitProcedureItem`
 * docstring: the mutual exclusivity is per-item, never per-visit).
 *
 * `items` is `[{ key, procedure_id, name, amount }]` — a stable local
 * `key` (generated here, never sent to the server) since a not-yet-
 * saved row has no real id yet. `onChange(items)` receives the full
 * updated array on every add/remove — a plain controlled list, not
 * react-hook-form's own field array, since the only cross-item
 * validation needed ("at least one procedure") belongs to whichever
 * parent form is submitting this list, not to each row individually. */
export function ProcedureItemsEditor({ items, onChange }) {
  const [selectedProcedure, setSelectedProcedure] = useState(null);
  const [manualName, setManualName] = useState('');
  const [manualAmount, setManualAmount] = useState('');
  const [addError, setAddError] = useState(null);

  const total = items.reduce((sum, item) => sum + Number(item.amount || 0), 0);

  function handleAddCatalog() {
    if (!selectedProcedure) return;
    onChange([
      ...items,
      {
        key: nextItemKey(),
        procedure_id: selectedProcedure.id,
        name: selectedProcedure.name,
        amount: selectedProcedure.price,
      },
    ]);
    setSelectedProcedure(null);
  }

  function handleAddManual() {
    setAddError(null);
    const trimmedName = manualName.trim();
    const amountNumber = Number(manualAmount);
    if (!trimmedName) {
      setAddError('Enter a procedure name.');
      return;
    }
    if (!Number.isFinite(amountNumber) || amountNumber <= 0) {
      setAddError('Enter an amount greater than 0.');
      return;
    }
    onChange([
      ...items,
      { key: nextItemKey(), procedure_id: null, name: trimmedName, amount: amountNumber },
    ]);
    setManualName('');
    setManualAmount('');
  }

  function handleRemove(key) {
    onChange(items.filter((item) => item.key !== key));
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label>From Procedure Catalog</Label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="flex-1">
            <SearchSelect
              queryKey={['visits', 'procedures', 'search']}
              queryFn={(term) =>
                proceduresService.searchProcedures(term).then((res) => res.data)
              }
              getLabel={(procedure) => procedure.name}
              getDescription={(procedure) => money(procedure.price)}
              placeholder="Search procedure by name"
              selectedLabel={selectedProcedure ? selectedProcedure.name : ''}
              onSelect={(procedure) => setSelectedProcedure(procedure)}
            />
          </div>
          <Button type="button" onClick={handleAddCatalog} disabled={!selectedProcedure}>
            <Plus className="h-4 w-4" />
            Add
          </Button>
        </div>
      </div>

      {/* Manual/free-text fallback (always available, never blocked on
          the catalog having this procedure yet) — coexists with
          catalog-linked rows in the same list. */}
      <div className="flex flex-col gap-3 rounded-md border border-dashed border-border p-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="flex min-w-[160px] flex-1 flex-col gap-1.5">
          <Label htmlFor="manual-procedure-name">Not in the catalog? Type it in</Label>
          <Input
            id="manual-procedure-name"
            placeholder="e.g. Follow-up"
            value={manualName}
            onChange={(event) => setManualName(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5 sm:w-40">
          <Label htmlFor="manual-procedure-amount">Amount (Rs.)</Label>
          <Input
            id="manual-procedure-amount"
            type="number"
            step="0.01"
            min="0"
            value={manualAmount}
            onChange={(event) => setManualAmount(event.target.value)}
          />
        </div>
        <Button type="button" variant="outline" onClick={handleAddManual}>
          <Plus className="h-4 w-4" />
          Add Another Procedure
        </Button>
      </div>
      {addError ? <p className="text-xs text-destructive">{addError}</p> : null}

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No procedures added yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Procedure</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.key}>
                <TableCell className="font-medium text-foreground">
                  {item.name}
                  {item.procedure_id ? (
                    <span className="ml-2 text-xs font-normal text-muted-foreground">
                      (catalog)
                    </span>
                  ) : null}
                </TableCell>
                <TableCell className="text-right tabular-nums">{money(item.amount)}</TableCell>
                <TableCell>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => handleRemove(item.key)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <div className="flex items-center justify-between border-t border-border pt-3">
        <span className="text-sm font-semibold text-foreground">Procedures Total</span>
        <span className="text-lg font-bold tabular-nums text-foreground">{money(total)}</span>
      </div>
    </div>
  );
}

/** Converts one editor row into the `{procedure_id, name, amount}`
 * request shape `POST /reception/visits`/`PATCH /reception/visits/{id}`
 * expect — a catalog-linked row omits name/amount entirely (server-
 * derived, see VisitProcedureItemRequest's own docstring), a manual row
 * omits procedure_id. */
export function procedureItemToRequestPayload(item) {
  if (item.procedure_id) {
    return { procedure_id: item.procedure_id };
  }
  return { name: item.name, amount: Number(item.amount) };
}
