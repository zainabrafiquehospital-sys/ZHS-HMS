"""FastAPI dependency-injection provider for the shared Email service —
see app/modules/patients/dependencies.py's identical module docstring
for the request-scoped-provider convention this follows."""

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.shared.email.service import EmailService


def get_email_service(settings: Settings = Depends(get_settings)) -> EmailService:
    return EmailService(settings)
