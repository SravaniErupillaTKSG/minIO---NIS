"""
IBML Scanner Ingestion — placeholder for future hardware integration.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: NOT IMPLEMENTED
Implement when IBML connectivity details are confirmed with the hardware team.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IBML scanners can submit documents via several transports.
Implement the one that matches the scanner model / network topology:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Option A — REST API push (recommended for modern IBML models)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IBML sends a POST to a webhook endpoint after each scan.
  Payload: { "scan_id": str, "file_b64": str, "content_type": str, "metadata": {} }
  Implementation: IBMLIngestion.from_rest_push(payload)
    - decode base64 file_data
    - validate content_type
    - set source_name = "IBML_SCANNER"
  Requires: a new FastAPI route POST /api/v1/ibml/push (protected by IBML-specific key)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Option B — SFTP drop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IBML places scanned files on an SFTP server.
  A poller (Celery beat task) monitors the drop folder and calls this class.
  Implementation: IBMLIngestion.from_sftp(remote_path)
    - connect via paramiko (pip install paramiko)
    - read file bytes
    - parse file_name + content_type from remote_path
    - set source_name = "IBML_SFTP"
  Requires: SFTP host/user/key in Settings; Celery beat schedule

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Option C — Shared network folder / drop location
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IBML writes files to a monitored directory on the LAN.
  A filesystem watcher (watchdog) detects new files and triggers processing.
  Implementation: IBMLIngestion.from_folder(file_path)
    - open / read the file
    - detect content_type via mimetypes.guess_type
    - set source_name = "IBML_FOLDER"
  Requires: watchdog (pip install watchdog); mount / shared drive config

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Source identifiers (set scan_source to one of these):
  "IBML_SCANNER"   — live scanner, REST push
  "IBML_SFTP"      — file received from SFTP drop
  "IBML_FOLDER"    — file received from network folder watcher
  "IBML_SIMULATED" — local dev / integration testing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

from app.ingestion.base_ingestion import BaseIngestion, IngestionDocument


class IBMLIngestion(BaseIngestion):
    """
    Placeholder for IBML scanner ingestion.
    Use the class-method factories (from_rest_push, from_sftp, from_folder)
    once the transport mechanism is confirmed. Direct instantiation raises.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "IBMLIngestion is a placeholder. "
            "Implement from_rest_push(), from_sftp(), or from_folder() "
            "based on the confirmed IBML transport mechanism."
        )

    @property
    def source_name(self) -> str:  # pragma: no cover
        return "IBML_SCANNER"

    async def to_document(self) -> IngestionDocument:  # pragma: no cover
        raise NotImplementedError

    # ── Future factory methods ─────────────────────────────────────────────────

    @classmethod
    def from_rest_push(cls, payload: dict) -> "IBMLIngestion":
        """Receive a document pushed by IBML via REST webhook (Option A)."""
        raise NotImplementedError("REST push ingestion not yet implemented.")

    @classmethod
    def from_sftp(cls, remote_path: str) -> "IBMLIngestion":
        """Fetch a document from an SFTP drop location (Option B)."""
        raise NotImplementedError("SFTP ingestion not yet implemented.")

    @classmethod
    def from_folder(cls, file_path: str) -> "IBMLIngestion":
        """Read a document from a monitored network folder (Option C)."""
        raise NotImplementedError("Folder-watch ingestion not yet implemented.")
