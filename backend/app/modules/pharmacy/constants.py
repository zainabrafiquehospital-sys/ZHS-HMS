"""Permission codes for the Pharmacy / Medicine Billing module.

Split the same way Billing's constants.py is (see that module's
docstring): `pharmacy:read` and `pharmacy:bill` are granted to the
Receptionist role (search the price list, build and print a medicine
bill), while `pharmacy:manage` — creating/editing/deactivating the
medicine price list itself — is granted only to `admin` (via the launch
bootstrap seed script's "admin gets every permission" rule; see
scripts/seed_launch_bootstrap.py). This module's code never enforces
*who* holds which permission — that is a role-assignment/deployment
concern (Phase 5 RBAC, frozen) — but the codes are split precisely along
this line so that assignment is possible in the first place."""

PERMISSION_PHARMACY_READ = "pharmacy:read"
PERMISSION_PHARMACY_BILL = "pharmacy:bill"
PERMISSION_PHARMACY_MANAGE = "pharmacy:manage"
