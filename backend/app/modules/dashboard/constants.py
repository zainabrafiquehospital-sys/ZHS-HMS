"""Permission codes for the Dashboard module — one per role-facing view
(Phase 6 §22: "Each dashboard only displays data allowed by RBAC"),
split so a role can be granted exactly the dashboards it should see and
no others. Minimal-build scope: Reception, Doctor, and Vitals dashboards
only — HR/Admin/Owner dashboards depend on Attendance/Shift data this
build does not include (out of scope per the MVP module list)."""

PERMISSION_DASHBOARD_RECEPTION_READ = "dashboard:reception:read"
PERMISSION_DASHBOARD_DOCTOR_READ = "dashboard:doctor:read"
PERMISSION_DASHBOARD_VITALS_READ = "dashboard:vitals:read"
