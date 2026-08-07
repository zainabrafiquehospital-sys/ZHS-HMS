"""SQLAlchemy models for the Patient module (Phase 6 architecture §3:
"Demographic/clinical identity, independent of any single visit").
Registered once into app/db/base.py's centralized model registry, same
convention as every other module (see app/modules/auth/models.py).

`Patient` deliberately owns no Visit/Queue/Billing state — those live in
their own modules (`visits`, `queue`, `billing`) per the frozen
architecture's module-ownership table and one-directional dependency
graph (§12): those modules read/reference a Patient, a Patient never
reads/references them.

`mr_number` is this hospital's permanent per-patient medical-record
identifier — distinct from a Visit's Queue Token (§18 of the
architecture, not yet built): the MR number identifies the *person*
across every visit they will ever have; the Queue Token identifies one
single visit. It is server-generated (see `PatientRepository.
next_mr_number`), never client-supplied, and immutable once assigned."""

from enum import Enum as PyEnum

from sqlalchemy import Enum, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity


class PatientGender(PyEnum):
    FEMALE = "female"
    MALE = "male"
    OTHER = "other"


class Patient(BaseEntity):
    """A patient's demographic/clinical identity. Visits, Queue Entries,
    Vitals, Consultations, and Invoices all reference a Patient (via
    Visit); a Patient never references any of them — see this module's
    docstring."""

    __tablename__ = "patient"
    __table_args__ = (
        Index(
            "ix_patient_mr_number_active",
            "mr_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Partial unique index: multiple active rows with cnic IS NULL are
        # allowed (Postgres never treats two NULLs as equal for uniqueness
        # purposes), but two active rows can never share the same non-null
        # CNIC — mirrors app/modules/auth/models.py's User.email/
        # phone_number pattern exactly.
        Index(
            "ix_patient_cnic_active",
            "cnic",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_patient_phone_number", "phone_number"),
        Index("ix_patient_full_name", "full_name"),
    )

    mr_number: Mapped[str] = mapped_column(String(20), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    guardian_name: Mapped[str | None] = mapped_column(String(150))
    # Optional at fast-registration time (only full_name/age_years/
    # phone_number are compulsory — see reception/schemas.py) — a real
    # high-volume OPD counter cannot demand a gender pick to register a
    # visit; it can always be filled in later via PATCH.
    gender: Mapped[PatientGender | None] = mapped_column(
        Enum(
            PatientGender,
            name="patient_gender",
            native_enum=False,
            length=10,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
    )
    # The patient's age in whole years, as stated by the patient/attendant
    # at registration — recorded directly, never calculated or derived
    # from any date. There is deliberately no date-of-birth field: Phase 6
    # originally modeled DOB with an "approximate age" fallback for
    # patients who didn't know it, but the hospital's actual OPD intake
    # only ever records age, so the fallback became the only field and
    # was promoted to the sole, required source of a patient's age.
    age_years: Mapped[int] = mapped_column(nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    cnic: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(Text())
