"""Channels that poll (Gmail) see the same message repeatedly; ingestion must be idempotent."""
import pytest

from app.core.errors import ConflictError, ValidationError
from app.repositories.quotations import QuotationRepository
from app.schemas.common import SourceType
from app.services.documents.detection import is_allowed_upload
from app.services.documents.ingestion import (
    IngestionPayload,
    ingest_document,
    ingest_document_once,
)

PDF_BYTES = b"%PDF-1.4\n% test quotation\n"


def _payload(reference):
    return IngestionPayload(
        data=PDF_BYTES,
        filename="quote.pdf",
        mime_type="application/pdf",
        source_type=SourceType.EMAIL,
        external_reference=reference,
    )


def test_plain_text_is_an_accepted_upload():
    assert is_allowed_upload("email-123.txt", "text/plain")


async def test_same_reference_is_ingested_once(db, org_a, storage):
    repo = QuotationRepository(db)
    first, created_first = await ingest_document_once(
        _payload("gmail:msg-1:1"), organization_id=org_a["org_id"],
        uploaded_by=None, repository=repo, storage=storage,
    )
    second, created_second = await ingest_document_once(
        _payload("gmail:msg-1:1"), organization_id=org_a["org_id"],
        uploaded_by=None, repository=repo, storage=storage,
    )
    assert created_first is True
    assert created_second is False
    assert second["id"] == first["id"]
    assert await repo.count(org_a["org_id"]) == 1


async def test_reference_is_scoped_to_the_organization(db, org_a, org_b, storage):
    repo = QuotationRepository(db)
    _, created_a = await ingest_document_once(
        _payload("gmail:shared:1"), organization_id=org_a["org_id"],
        uploaded_by=None, repository=repo, storage=storage,
    )
    _, created_b = await ingest_document_once(
        _payload("gmail:shared:1"), organization_id=org_b["org_id"],
        uploaded_by=None, repository=repo, storage=storage,
    )
    assert created_a is True
    assert created_b is True


async def test_reference_is_required(db, org_a, storage):
    with pytest.raises(ValidationError):
        await ingest_document_once(
            _payload(None), organization_id=org_a["org_id"], uploaded_by=None,
            repository=QuotationRepository(db), storage=storage,
        )


async def test_database_rejects_a_racing_duplicate(db, org_a, storage):
    """The unique index is the backstop when two syncs pass the lookup together."""
    repo = QuotationRepository(db)
    await ingest_document(
        _payload("gmail:race:1"), organization_id=org_a["org_id"],
        uploaded_by=None, repository=repo, storage=storage,
    )
    with pytest.raises(ConflictError):
        await ingest_document(
            _payload("gmail:race:1"), organization_id=org_a["org_id"],
            uploaded_by=None, repository=repo, storage=storage,
        )


async def test_manual_uploads_without_a_reference_never_collide(db, org_a, storage):
    repo = QuotationRepository(db)
    for _ in range(2):
        await ingest_document(
            _payload(None), organization_id=org_a["org_id"],
            uploaded_by=None, repository=repo, storage=storage,
        )
    assert await repo.count(org_a["org_id"]) == 2
