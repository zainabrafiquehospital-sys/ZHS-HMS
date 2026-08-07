"""Permission codes for the Billing module. Split so RBAC can hold
Phase 6 §7's segregation of duties: a doctor role is granted only
`billing:submit_charge` (they can request a charge, nothing else); the
Reception/billing-counter role is granted `billing:read` and
`billing:manage` (review, approve/reject, generate invoices, record
payment). This module's code never enforces *who* holds which
permission — that is a role-assignment/deployment concern (Phase 5
RBAC, frozen) — but the permission codes themselves are split precisely
along this line so that assignment is possible in the first place."""

PERMISSION_BILLING_SUBMIT_CHARGE = "billing:submit_charge"
PERMISSION_BILLING_READ = "billing:read"
PERMISSION_BILLING_MANAGE = "billing:manage"
