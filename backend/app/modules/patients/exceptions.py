"""Patient-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one — so every
endpoint in the app, patients or otherwise, produces the same error
envelope and status-code mapping (see app/modules/auth/exceptions.py's
identical module docstring for the same principle applied there)."""

from app.core.exceptions import ConflictError, NotFoundError


class PatientNotFoundError(NotFoundError):
    code = "PATIENT_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Patient not found.")


class PatientCnicAlreadyExistsError(ConflictError):
    code = "PATIENT_CNIC_ALREADY_EXISTS"

    def __init__(self) -> None:
        super().__init__("A patient with this CNIC is already registered.")
