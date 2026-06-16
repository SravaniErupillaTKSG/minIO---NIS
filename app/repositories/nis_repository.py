"""
NIS Master repository — all database operations for the nis_master table.

Pattern:
  - Every method accepts a SQLAlchemy Session (injected by FastAPI Depends).
  - Methods return SQLAlchemy ORM objects (NISMaster) — the service layer converts
    these to Pydantic schemas before returning them to the endpoint.
  - No raw SQL — use SQLAlchemy ORM throughout.
  - Raises ValueError on business-rule violations (duplicate nis_id, not found)
    so the service layer can translate to the appropriate HTTP exception.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.nis_master import NISMaster


class NISRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Writes ────────────────────────────────────────────────────────────────

    def create(
        self,
        nis_id:      str,
        person_name: str,
        entity_type: str,
    ) -> NISMaster:
        """
        Insert a new NIS person record.
        Raises ValueError if nis_id already exists (caller should catch and return 409).
        """
        if self.exists(nis_id):
            raise ValueError(f"NIS ID '{nis_id}' is already registered.")

        record = NISMaster(
            nis_id=nis_id,
            person_name=person_name,
            entity_type=entity_type,
        )
        self._db.add(record)
        self._db.commit()
        self._db.refresh(record)
        return record

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_by_id(self, nis_id: str) -> Optional[NISMaster]:
        """Return the NISMaster row or None if not found."""
        return (
            self._db.query(NISMaster)
            .filter(NISMaster.nis_id == nis_id)
            .first()
        )

    def exists(self, nis_id: str) -> bool:
        """Fast existence check — does not load the full row."""
        return (
            self._db.query(NISMaster.nis_id)
            .filter(NISMaster.nis_id == nis_id)
            .first()
        ) is not None

    def list_all(self, skip: int = 0, limit: int = 100) -> List[NISMaster]:
        """Return a paginated list of all NIS persons, ordered by creation date."""
        return (
            self._db.query(NISMaster)
            .order_by(NISMaster.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
