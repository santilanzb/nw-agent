"""
Fetching and keeping what a patient sends.

`waha.py` used to return `None` for every image and voice note, so payment
proofs vanished. Stage 0 stopped the dropping; the FSM still only acknowledged
them, so an asesora picking up the conversation saw the word "[image]" and had
to go find the receipt in WhatsApp herself.

Three rules this module exists to hold:

- **The bytes go to disk, the reference goes everywhere else.** Graft 10 forbids
  patient content in Zoho Notes and the team group; a photo of a bank transfer is
  the most identifying thing in the system.
- **Every stored file has a row.** A directory of media nobody has a record for
  is precisely the store an Art. 17 erasure drill discovers too late.
- **A fetch failure is recorded, not swallowed.** The asesora is told there was
  an attachment she cannot see, which is recoverable. Silence is not.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from psycopg_pool import AsyncConnectionPool

from ..transport.base import InboundMedia

logger = logging.getLogger(__name__)

# A voice note is small; a photo from a modern phone is not. Beyond this we keep
# the row and skip the bytes rather than filling the volume with one video.
MAX_MEDIA_BYTES = 25 * 1024 * 1024

_TIMEOUT = httpx.Timeout(connect=3.0, read=20.0, write=5.0, pool=3.0)

RECORD_ARTIFACT = """
INSERT INTO media_artifacts (
    identity_id, turn_id, source, provider_media_id, kind, mime_type,
    byte_size, sha256, storage_path, caption, status, last_error
) VALUES (
    %(identity_id)s, %(turn_id)s, %(source)s, %(provider_media_id)s, %(kind)s, %(mime_type)s,
    %(byte_size)s, %(sha256)s, %(storage_path)s, %(caption)s, %(status)s, %(last_error)s
)
ON CONFLICT (identity_id, sha256) WHERE identity_id IS NOT NULL AND sha256 IS NOT NULL
DO UPDATE SET turn_id = EXCLUDED.turn_id
RETURNING id
"""


@dataclass(frozen=True, slots=True)
class StoredMedia:
    """What the asesora is given: a reference, never the content."""

    id: uuid.UUID | None
    kind: str
    stored: bool
    reference: str

    @property
    def summary(self) -> str:
        if self.stored:
            return f"{self.kind} · ref {self.reference}"
        return f"{self.kind} · NO SE PUDO DESCARGAR ({self.reference})"


class MediaStore:
    def __init__(self, pool: AsyncConnectionPool, root: str, *, api_key: str = "") -> None:
        self._pool = pool
        self._root = Path(root)
        self._headers = {"X-Api-Key": api_key} if api_key else {}

    def _destination(self, artifact_id: uuid.UUID, mime_type: str | None) -> Path:
        """
        Sharded by day so one directory never holds a year of receipts, and so a
        retention sweep can reason about whole days.
        """
        suffix = mimetypes.guess_extension(mime_type or "") or ".bin"
        day = datetime.now(UTC).strftime("%Y/%m/%d")
        return self._root / day / f"{artifact_id}{suffix}"

    async def _fetch(self, url: str) -> bytes | None:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.content
        if len(payload) > MAX_MEDIA_BYTES:
            logger.warning("media too large (%d bytes) — keeping the record only", len(payload))
            return None
        return payload

    async def store(
        self,
        media: InboundMedia,
        *,
        identity_id: uuid.UUID | None,
        turn_id: uuid.UUID,
        source: str,
    ) -> StoredMedia:
        """
        Fetch, write and record. Never raises: a patient who sent a receipt still
        gets an answer, and the asesora is told the attachment could not be
        retrieved rather than being told nothing.
        """
        artifact_id = uuid.uuid4()
        payload: bytes | None = None
        error: str | None = None

        if media.url:
            try:
                payload = await self._fetch(media.url)
                if payload is None:
                    error = "media exceeded the size limit"
            except Exception as exc:  # noqa: BLE001 - a failed download is a note, not an outage
                error = f"{type(exc).__name__}: {exc}"
                logger.warning("media fetch failed kind=%s: %s", media.kind, error)
        else:
            error = "transport supplied no media url"

        storage_path = ""
        digest = None
        if payload is not None:
            digest = hashlib.sha256(payload).hexdigest()
            destination = self._destination(artifact_id, media.mime_type)
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
                storage_path = str(destination.relative_to(self._root))
            except OSError as exc:
                error = f"write failed: {exc}"
                logger.exception("media write failed kind=%s", media.kind)
                payload = None

        status = "stored" if payload is not None and not error else "fetch_failed"
        stored_id = await self._record(
            artifact_id,
            media=media,
            identity_id=identity_id,
            turn_id=turn_id,
            source=source,
            byte_size=len(payload) if payload is not None else None,
            digest=digest,
            storage_path=storage_path,
            status=status,
            error=error,
        )

        return StoredMedia(
            id=stored_id,
            kind=media.kind,
            stored=status == "stored",
            reference=str(stored_id)[:8] if stored_id else (error or "sin referencia"),
        )

    async def _record(
        self,
        artifact_id: uuid.UUID,
        *,
        media: InboundMedia,
        identity_id: uuid.UUID | None,
        turn_id: uuid.UUID,
        source: str,
        byte_size: int | None,
        digest: str | None,
        storage_path: str,
        status: str,
        error: str | None,
    ) -> uuid.UUID | None:
        params = {
            "identity_id": identity_id,
            "turn_id": turn_id,
            "source": source,
            "provider_media_id": media.provider_media_id,
            "kind": media.kind,
            "mime_type": media.mime_type,
            "byte_size": byte_size,
            "sha256": digest,
            "storage_path": storage_path,
            "caption": (media.caption or None),
            "status": status,
            "last_error": error,
        }
        try:
            async with self._pool.connection() as conn:
                cur = await conn.execute(RECORD_ARTIFACT, params)
                row = await cur.fetchone()
                return row["id"] if row else None
        except Exception:
            logger.exception("media_artifacts write failed turn=%s", turn_id)
            return None
