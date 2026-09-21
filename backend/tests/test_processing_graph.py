"""The processing pipeline runs as a LangGraph graph and records each agent step."""
import json

from app.repositories.automation import AgentRunRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.quotations import PriceHistoryRepository, QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.common import SourceType
from app.services.documents.ingestion import IngestionPayload, ingest_document
from app.services.documents.pipeline import ProcessingPipeline

QUOTE = b"""SHREE STEEL TRADERS
GST No: 27AABCS1429B1ZQ
Quotation No: Q-101
Item            Qty   Rate    Amount
MS plate 10mm   100   72.00   7200.00
Grand Total 7200.00
Delivery: 7 days
"""


async def run(db, org, storage, data):
    quotations = QuotationRepository(db)
    quotation = await ingest_document(
        IngestionPayload(data=data, filename="quote.txt", mime_type="text/plain", source_type=SourceType.MANUAL_UPLOAD),
        organization_id=org["org_id"], uploaded_by=None, repository=quotations, storage=storage
    )
    pipeline = ProcessingPipeline(
        quotations=quotations, suppliers=SupplierRepository(db), requests=ProcurementRequestRepository(db),
        price_history=PriceHistoryRepository(db), storage=storage, runs=AgentRunRepository(db),
    )
    result = await pipeline.run(org["org_id"], quotation["id"])
    runs = await AgentRunRepository(db).list(org["org_id"])
    return result, runs[0]


async def test_a_quotation_passes_every_agent_in_order(db, org_a, storage):
    result, agent_run = await run(db, org_a, storage, QUOTE)
    assert result["processing_status"] in ("COMPLETED", "REQUIRES_REVIEW")
    assert result["supplier_name"] and result["normalized_data"]["items"]
    assert agent_run["graph"] == "quotation_processing" and agent_run["status"] == "completed"
    assert [s["agent"] for s in agent_run["steps"]] == [
        "Document Extraction Agent", "Normalization Agent", "Supplier Resolution", "Matching Agent", "Finalize"]
    assert all(s["error"] is None and s["finished_at"] for s in agent_run["steps"])


async def test_an_empty_document_takes_the_fail_edge(db, org_a, storage):
    result, agent_run = await run(db, org_a, storage, b"   \n")
    assert result["processing_status"] == "FAILED"
    assert [s["action"] for s in agent_run["steps"]] == ["extract and validate", "fail"]


def _extraction(unit_price: float) -> str:
    """One quotation line, as the model would return it."""
    return json.dumps({
        "supplier": {"name": "Shree Steel Traders", "gst_number": "27AABCS1429B1ZQ"},
        "items": [{"original_name": "MS plate 10mm", "quantity": 100, "unit": "kg",
                   "unit_price": unit_price, "total_price": abs(unit_price) * 100}],
        "pricing": {"currency": "INR", "total_amount": abs(unit_price) * 100},
        "delivery": {"delivery_days": 7},
    })


async def test_the_extraction_agent_corrects_itself_when_validation_finds_errors(db, org_a, storage, monkeypatch):
    from app.services.documents import ai_extraction
    from tests.fakes.llm import ScriptedProvider

    # First reading misreads the price as negative; the second, after feedback, is right.
    provider = ScriptedProvider(responses=[_extraction(-72.0), _extraction(72.0)])
    monkeypatch.setattr(ai_extraction, "get_ai_provider", lambda task=None: provider)

    result, agent_run = await run(db, org_a, storage, QUOTE)

    assert len(provider.calls) == 2
    assert "problems were found" in provider.calls[1]["prompt"]
    assert "negative" in provider.calls[1]["prompt"].lower()
    assert result["ai_extraction"]["items"][0]["unit_price"] == 72.0
    assert result["validation"]["error_count"] == 0
    assert "Corrected after a validation check" in " ".join(result["ai_extraction"]["notes"])
    assert "self-correction" in next(s["summary"] for s in agent_run["steps"] if s["agent"] == "Document Extraction Agent")


async def test_a_clean_extraction_is_not_read_twice(db, org_a, storage, monkeypatch):
    from app.services.documents import ai_extraction
    from tests.fakes.llm import ScriptedProvider

    provider = ScriptedProvider(responses=[_extraction(72.0)])
    monkeypatch.setattr(ai_extraction, "get_ai_provider", lambda task=None: provider)
    await run(db, org_a, storage, QUOTE)
    assert len(provider.calls) == 1
