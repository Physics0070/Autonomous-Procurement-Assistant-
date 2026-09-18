"""The processing pipeline runs as a LangGraph graph and records each agent step."""
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
