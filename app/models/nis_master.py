"""
NIS Master table — one row per registered person (Contributor / Beneficiary / Employee).

Why this table exists:
  Documents are meaningless without knowing WHO they belong to. This table is
  the authoritative registry of NIS persons. Every document_metadata row has
  a foreign key here, enforcing referential integrity.

Design decisions:
  - nis_id is user-supplied (business assigns it, e.g. "NIS001"), NOT auto-generated.
    This mirrors how NIS operates: the ID is known before the person enters the system.
  - entity_type is stored as a plain string (not an Enum column) so we can add new
    types without a database migration — just update the validation in the API layer.
  - updated_at uses onupdate=func.now() so SQLAlchemy auto-stamps it on any UPDATE.
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, String
from sqlalchemy.sql import func

from app.core.database import Base


class NISMaster(Base):
    __tablename__ = "nis_master"

    nis_id      = Column(String(50),  primary_key=True, index=True)
    person_name = Column(String(255), nullable=False)
    entity_type = Column(String(50),  nullable=False)   # CONTRIBUTOR | BENEFICIARY | EMPLOYEE
    created_at  = Column(DateTime,    nullable=False, default=func.now())
    updated_at  = Column(DateTime,    nullable=True,  onupdate=func.now())

    def __repr__(self) -> str:
        return f"<NISMaster nis_id={self.nis_id!r} entity_type={self.entity_type!r}>"
