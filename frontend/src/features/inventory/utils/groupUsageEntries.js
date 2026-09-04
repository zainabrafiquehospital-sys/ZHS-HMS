/** Collapses `entries` (individual `InventoryUsageEntry` rows, each item
 * its own row by design — see backend/app/modules/inventory/models.py's
 * own "no batch/session parent entity" docstring) back into one group
 * per actual "Record Usage" submission — real-world feedback: a
 * receptionist recording 4 items against one patient in one sitting saw
 * 4 separate rows, all identical except the item, and had no way to see
 * them as the one action they actually were.
 *
 * There is no batch id to group by (deliberately, per that same
 * docstring), but every line inserted by one `record_usage` call shares
 * the exact same `created_at` — confirmed directly against a real
 * 3-item batch: Postgres's `now()` (the `server_default` this column
 * uses) is frozen for the lifetime of one transaction, and
 * `record_usage` writes its whole batch, then commits, in exactly one
 * transaction — so `created_at` down to the microsecond is a reliable
 * grouping key here, not a coincidence. Combined with
 * `patient_display_name` (already-resolved, so two different
 * anonymous/manual entries never merge unless they're also the exact
 * same submission) rather than raw `patient_id`, which is `null` for
 * both the fully-anonymous and manual-name cases and would otherwise
 * collide across genuinely different batches recorded in the same
 * process tick.
 *
 * Originally private to MyInventoryUsage.jsx (its own "My Inventory
 * Usage" list, scoped to the calling actor); extracted here verbatim
 * (2026-09-04) so the new hospital-wide Daily Usage view
 * (DailyInventoryUsage.jsx) groups its own — much larger, multi-actor —
 * result set the identical way, rather than reinventing the grouping
 * key. Grouping happens within the current result set only (the same
 * "current volume" scope every other client-side grouping in this
 * codebase already accepts) — a batch split across a page boundary is a
 * real but rare edge case, not worth a server-side redesign for. */
export function groupUsageEntries(entries) {
  const groups = new Map();
  for (const entry of entries) {
    const key = `${entry.created_at}::${entry.patient_display_name ?? ''}`;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        createdAt: entry.created_at,
        usedOn: entry.used_on,
        patientId: entry.patient_id,
        manualPatientName: entry.manual_patient_name,
        patientDisplayName: entry.patient_display_name,
        createdBy: entry.created_by,
        createdByDisplayName: entry.created_by_display_name,
        lines: [],
      });
    }
    groups.get(key).lines.push(entry);
  }
  return Array.from(groups.values());
}
