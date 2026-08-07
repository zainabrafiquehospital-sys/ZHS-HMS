# Feature Modules

This folder is intentionally empty in the Phase 1 scaffold. No business
features are implemented at this stage.

Every future feature module (Authentication, Patients, Reception, Vitals,
Doctor Consultation, Prescription, Admission, Discharge, Dashboard, Reports,
Settings, Audit Logs, etc.) is added here as its own folder, following the
same fixed internal shape:

```
features/<feature-name>/
├── components/   feature-scoped UI, never imported by another feature
├── hooks/        feature-local hooks (derived state, form orchestration)
├── api/          query/mutation hooks wrapping the shared HTTP client
├── schemas/      form validation schemas, paired with backend request schemas
└── constants.js  enums, option lists, status labels
```

A component, hook, or utility needed by more than one feature does not stay
inside a feature folder — it moves to `src/shared`.
