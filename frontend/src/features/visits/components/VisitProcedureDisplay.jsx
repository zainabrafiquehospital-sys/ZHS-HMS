function money(amount) {
  return `Rs. ${Number(amount).toFixed(2)}`;
}

/** Renders a Visit's procedure breakdown for any read-only list/detail
 * view (2026-08-21 addition) — itemized, each procedure on its own
 * line with its own amount, when the visit has `procedure_items`;
 * falls back to the single legacy `procedure` string for a visit with
 * none (permanently — see backend/app/modules/visits/models.py's
 * `VisitProcedureItem` docstring). Never re-joins multiple procedures
 * into one combined string, even inside a compact table cell — a
 * confirmed, explicit requirement — each procedure is its own line
 * here regardless of how many other columns/rows surround it. Used
 * everywhere `visit.procedure` used to be rendered directly:
 * MyRegistrations, DoctorQueueList, BillingWorklist,
 * PatientVisitHistoryDialog, AdminOverview's visits table,
 * MedicineBillingWorkspace's visit-link panel, BillingWorkspace's
 * visit-summary header. */
export function VisitProcedureDisplay({ visit, className }) {
  if (visit.procedure_items?.length > 0) {
    return (
      <div className={className}>
        {visit.procedure_items.map((item) => (
          <div key={item.id}>
            {item.name} <span className="text-muted-foreground">({money(item.amount)})</span>
          </div>
        ))}
      </div>
    );
  }
  return <span className={className}>{visit.procedure}</span>;
}
