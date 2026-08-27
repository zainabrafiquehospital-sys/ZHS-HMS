"""Permission codes for the Laboratory Billing module.

Split exactly the same way app/modules/pharmacy/constants.py's identical
codes are: `lab:read` and `lab:bill` are granted to the Receptionist
role (search the test catalog, build and print a lab bill), while
`lab:manage` — creating/editing/deactivating the lab test price list
itself — is granted only to `admin` (via the launch bootstrap seed
script's "admin gets every permission" rule; see scripts/
seed_launch_bootstrap.py). This module's code never enforces *who*
holds which permission — that is a role-assignment/deployment concern
— but the codes are split precisely along this line so that assignment
is possible in the first place."""

PERMISSION_LAB_READ = "lab:read"
PERMISSION_LAB_BILL = "lab:bill"
PERMISSION_LAB_MANAGE = "lab:manage"

# Admin-only data-correction actions — mirrors app/modules/pharmacy/
# constants.py's identical PERMISSION_PHARMACY_UPDATE_BILL/
# PERMISSION_PHARMACY_DELETE_BILL pair exactly: two separate, atomic
# permission codes (not folded into `lab:manage`, which is about the
# test price list, a different resource entirely) so update/delete
# could be granted independently through the Roles/Permissions API
# without a code change. Neither is ever granted to the Receptionist
# role — receptionists keep exactly the read/bill capability they had
# before; correcting or removing a mistakenly-created bill is an admin
# data-integrity tool, not a front-desk action.
PERMISSION_LAB_UPDATE_BILL = "lab:update_bill"
PERMISSION_LAB_DELETE_BILL = "lab:delete_bill"
