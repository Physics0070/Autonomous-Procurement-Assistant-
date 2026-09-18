"""The processing pipeline.

    QUEUED -> EXTRACTING -> AI_EXTRACTING -> NORMALIZING
           -> COMPLETED | REQUIRES_REVIEW | FAILED

Each stage writes its own output to its own field, so nothing overwrites an
earlier stage. The original file and the raw extraction survive everything that
happens afterwards, including user corrections.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.errors import NotFoundError
from app.repositories.automation import AgentRunRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.quotations import PriceHistoryRepository, QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.common import ProcessingStatus, SourceType
from app.services.documents.ai_extraction import extract_structured
from app.services.documents.processor import process_document
from app.services.procurement.anomaly import detect_price_anomaly
from app.services.procurement.matching import match_items
from app.services.procurement.normalization import normalize_text
from app.services.procurement.normalizer_service import normalize_quotation
from app.services.procurement.reliability import compute_reliability
from app.services.procurement.validation import validate_extraction
from app.services.agents.runs import RunRecorder
from app.services.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class ProcessingState(TypedDict, total=False):
    org: str
    qid: str
    quotation: dict[str, Any]
    processed: Any
    extraction: Any
    ai_error: Optional[str]
    validation: Any
    normalized: Any
    supplier_id: Any
    failure: Optional[str]
    result: dict[str, Any]


class ProcessingPipeline:
    """Quotation processing as a LangGraph state graph:

        document_extraction -> normalization -> supplier_resolution -> matching -> finalize
                  \\-> fail (no readable content)
    """

    def __init__(
        self,
        *,
        quotations: QuotationRepository,
        suppliers: SupplierRepository,
        requests: ProcurementRequestRepository,
        price_history: PriceHistoryRepository,
        storage: StorageBackend,
        runs: Optional[AgentRunRepository] = None,
    ):
        self.quotations = quotations
        self.suppliers = suppliers
        self.requests = requests
        self.price_history = price_history
        self.storage = storage
        self.runs = runs

    def _graph(self, recorder: RunRecorder):
        def node(agent: str, action: str, fn):
            async def run(state: ProcessingState) -> dict[str, Any]:
                async with recorder.step(agent, action) as step:
                    update = await fn(state)
                    step["summary"] = update.pop("_summary", "")
                    return update
            return run

        graph = StateGraph(ProcessingState)
        graph.add_node("document_extraction", node("Document Extraction Agent", "extract and validate", self._extract))
        graph.add_node("normalization", node("Normalization Agent", "normalize", self._normalize))
        graph.add_node("supplier_resolution", node("Supplier Resolution", "resolve supplier", self._resolve))
        graph.add_node("matching", node("Matching Agent", "match items", self._match))
        graph.add_node("finalize", node("Finalize", "set status", self._finalize))
        graph.add_node("fail", node("Finalize", "fail", self._fail_node))
        graph.add_edge(START, "document_extraction")
        graph.add_conditional_edges("document_extraction", lambda s: "fail" if s.get("failure") else "normalization")
        graph.add_edge("normalization", "supplier_resolution")
        graph.add_edge("supplier_resolution", "matching")
        graph.add_edge("matching", "finalize")
        graph.add_edge("finalize", END)
        graph.add_edge("fail", END)
        return graph.compile()

    async def run(self, organization_id: str, quotation_id: str) -> dict[str, Any]:
        """Process one quotation end to end. Never raises for data problems."""
        quotation = await self.quotations.get(organization_id, quotation_id)
        if quotation is None:
            raise NotFoundError("Quotation not found")

        recorder = await RunRecorder(self.runs, organization_id, "quotation_processing",
                                     {"quotation_id": quotation_id}).start()
        try:
            state = await self._graph(recorder).ainvoke({"org": organization_id, "qid": quotation_id, "quotation": quotation})
            result = state["result"]
        except Exception as exc:  # a pipeline crash must not lose the record
            logger.exception("Pipeline failed for quotation %s", quotation_id)
            await self.quotations.set_status(
                organization_id,
                quotation_id,
                ProcessingStatus.FAILED.value,
                message=f"Processing failed: {exc}",
                extra={"error": str(exc)},
            )
            result = await self.quotations.get_or_404(organization_id, quotation_id)
        await recorder.finish("completed", {"processing_status": result.get("processing_status")})
        return result

    async def _fail_node(self, state: ProcessingState) -> dict[str, Any]:
        return {"result": await self._fail(state["org"], state["qid"], state["failure"]), "_summary": state["failure"]}

    async def _extract(self, state: ProcessingState) -> dict[str, Any]:
        organization_id, quotation_id, quotation = state["org"], state["qid"], state["quotation"]
        source = quotation.get("source") or {}
        storage_key = source.get("storage_key")
        filename = source.get("original_filename") or "document"

        # Stage 1: raw extraction
        await self.quotations.set_status(
            organization_id, quotation_id, ProcessingStatus.EXTRACTING.value,
            message="Extracting text and tables from the document.",
        )
        if not storage_key:
            return {"failure": "No stored file is associated with this quotation."}

        try:
            data = await self.storage.load(storage_key)
        except Exception as exc:
            return {"failure": f"Stored file could not be read: {exc}"}

        try:
            source_type = SourceType(source.get("type") or SourceType.MANUAL_UPLOAD.value)
        except ValueError:
            source_type = SourceType.MANUAL_UPLOAD

        processed = await process_document(
            data,
            filename=filename,
            mime_type=source.get("mime_type"),
            source_type=source_type,
            quotation_id=quotation_id,
        )
        await self.quotations.store_stage(
            organization_id, quotation_id, "raw_content", processed.model_dump(mode="json")
        )
        await self.quotations.store_stage(
            organization_id, quotation_id, "document_type", processed.document_type.value
        )

        if not processed.raw_text.strip() and not processed.tables:
            reason = "; ".join(processed.extraction_errors) or "No readable content was found."
            return {"failure": f"Extraction produced no content. {reason}"}

        # Stage 2: AI structured extraction
        await self.quotations.set_status(
            organization_id, quotation_id, ProcessingStatus.AI_EXTRACTING.value,
            message="Extracting structured quotation data.",
            details={"ocr_used": processed.ocr_used, "chars": len(processed.raw_text)},
        )
        extraction, ai_error = await extract_structured(processed)
        await self.quotations.store_stage(
            organization_id, quotation_id, "ai_extraction", extraction.model_dump(mode="json")
        )

        # Stage 3: validation (flags only; never edits the extraction)
        validation = validate_extraction(extraction)
        await self.quotations.store_stage(
            organization_id, quotation_id, "validation", validation.model_dump(mode="json")
        )
        return {
            "processed": processed, "extraction": extraction, "ai_error": ai_error, "validation": validation,
            "_summary": f"{len(extraction.items)} items via {extraction.provider or 'heuristics'}; "
                        f"{validation.error_count} error(s), {validation.warning_count} warning(s)",
        }

    async def _normalize(self, state: ProcessingState) -> dict[str, Any]:
        organization_id, quotation_id = state["org"], state["qid"]
        await self.quotations.set_status(
            organization_id, quotation_id, ProcessingStatus.NORMALIZING.value,
            message="Normalizing products, units and commercial terms.",
        )
        normalized = normalize_quotation(state["extraction"])

        # Price anomaly per line, against this organization's own history.
        for item in normalized.items:
            if item.normalized_name and item.unit_price is not None:
                prices = await self.price_history.prices(organization_id, item.normalized_name)
                item.attributes["_price_anomaly"] = detect_price_anomaly(item.unit_price, history=prices)

        normalized_payload = normalized.model_dump(mode="json")
        await self.quotations.store_stage(
            organization_id, quotation_id, "normalized_data", normalized_payload
        )
        # effective_data starts as a copy of normalized_data; corrections layer
        # onto it without ever touching normalized_data itself.
        await self.quotations.store_stage(
            organization_id, quotation_id, "effective_data", normalized_payload
        )
        return {"normalized": normalized, "_summary": f"{len(normalized.items)} items normalized"}

    async def _resolve(self, state: ProcessingState) -> dict[str, Any]:
        organization_id, quotation_id, normalized = state["org"], state["qid"], state["normalized"]
        supplier_id = state["quotation"].get("supplier_id")
        supplier_name = normalized.supplier.name
        if not supplier_id and (normalized.supplier.gst_number or normalized.supplier.email or supplier_name):
            supplier = await self._resolve_supplier(organization_id, normalized)
            if supplier:
                supplier_id = supplier.get("id")
                supplier_name = supplier.get("name") or supplier_name
        if supplier_id:
            await self.quotations.store_stage(
                organization_id, quotation_id, "supplier_id", _oid(supplier_id)
            )
            normalized.supplier.supplier_id = str(supplier_id)
            await self.quotations.store_stage(
                organization_id, quotation_id, "normalized_data.supplier.supplier_id", str(supplier_id)
            )
            await self._refresh_reliability(organization_id, str(supplier_id))
        if supplier_name:
            await self.quotations.store_stage(organization_id, quotation_id, "supplier_name", supplier_name)
        return {"supplier_id": supplier_id, "_summary": supplier_name or "No supplier identified"}

    async def _match(self, state: ProcessingState) -> dict[str, Any]:
        organization_id, quotation_id, normalized = state["org"], state["qid"], state["normalized"]
        supplier_id = state.get("supplier_id")
        summary = "No linked procurement request"
        request_id = state["quotation"].get("procurement_request_id")
        if request_id:
            request = await self.requests.get(organization_id, str(request_id))
            if request and request.get("items"):
                match_result = await match_items(
                    request["items"],
                    normalized,
                    quotation_id=quotation_id,
                    procurement_request_id=str(request_id),
                )
                await self.quotations.store_stage(
                    organization_id, quotation_id, "match_result", match_result.model_dump(mode="json")
                )
                summary = f"{match_result.matched_count} of {len(request['items'])} requested items matched"

        # Record prices for future anomaly baselines
        for item in normalized.items:
            if item.normalized_name and item.unit_price is not None:
                await self.price_history.record(
                    organization_id,
                    item.normalized_name,
                    item.unit_price,
                    unit=item.normalized_unit,
                    supplier_id=str(supplier_id) if supplier_id else None,
                    quotation_id=quotation_id,
                )
        return {"_summary": summary}

    async def _finalize(self, state: ProcessingState) -> dict[str, Any]:
        organization_id, quotation_id = state["org"], state["qid"]
        processed, extraction, validation, normalized, ai_error = (
            state["processed"], state["extraction"], state["validation"], state["normalized"], state.get("ai_error"))
        confidence = self._confidence(processed, extraction, validation, normalized)
        await self.quotations.store_stage(organization_id, quotation_id, "confidence", confidence)
        await self.quotations.store_stage(
            organization_id,
            quotation_id,
            "total_amount",
            normalized.pricing.landed_total or normalized.pricing.total_amount,
        )
        await self.quotations.store_stage(
            organization_id, quotation_id, "currency", normalized.pricing.currency
        )
        await self.quotations.store_stage(
            organization_id, quotation_id, "item_count", len(normalized.items)
        )

        needs_review = validation.requires_review or bool(ai_error) or bool(normalized.missing_fields)
        status = ProcessingStatus.REQUIRES_REVIEW if needs_review else ProcessingStatus.COMPLETED
        message_parts = []
        if ai_error:
            message_parts.append(f"AI extraction degraded: {ai_error}")
        if validation.requires_review:
            message_parts.append(
                f"{validation.error_count} error(s), {validation.warning_count} warning(s) require review."
            )
        if normalized.missing_fields:
            message_parts.append(f"Missing fields: {', '.join(normalized.missing_fields[:6])}.")

        await self.quotations.set_status(
            organization_id,
            quotation_id,
            status.value,
            message="; ".join(message_parts) or "Processing completed successfully.",
            details={
                "items": len(normalized.items),
                "errors": validation.error_count,
                "warnings": validation.warning_count,
            },
            extra={
                "requires_review": needs_review,
                "issue_count": validation.error_count + validation.warning_count,
                "error": None,
            },
        )
        return {"result": await self.quotations.get_or_404(organization_id, quotation_id), "_summary": status.value}

    # ------------------------------------------------------------------
    async def _fail(self, organization_id: str, quotation_id: str, message: str) -> dict[str, Any]:
        await self.quotations.set_status(
            organization_id, quotation_id, ProcessingStatus.FAILED.value,
            message=message, extra={"error": message},
        )
        return await self.quotations.get_or_404(organization_id, quotation_id)

    async def _resolve_supplier(self, organization_id: str, normalized) -> Optional[dict[str, Any]]:
        """Find or create the supplier this quotation came from.

        GST number is the strongest identifier, then email, then an exact name.
        """
        supplier = None
        if normalized.supplier.gst_number:
            supplier = await self.suppliers.find_by_gst(organization_id, normalized.supplier.gst_number)
        if supplier is None and normalized.supplier.email:
            supplier = await self.suppliers.find_by_email(organization_id, normalized.supplier.email)
        if supplier is None and normalized.supplier.name:
            supplier = await self.suppliers.find_by_name(organization_id, normalized.supplier.name)
            if supplier is None:
                # Fall back to normalized-name comparison before creating a duplicate.
                target = normalize_text(normalized.supplier.name)
                for existing in await self.suppliers.all_names(organization_id):
                    if normalize_text(existing.get("name")) == target:
                        supplier = existing
                        break

        if supplier is not None:
            return supplier
        if not normalized.supplier.name:
            return None

        return await self.suppliers.create(
            organization_id,
            {
                "name": normalized.supplier.name,
                "email": normalized.supplier.email,
                "phone": normalized.supplier.phone,
                "gst_number": normalized.supplier.gst_number,
                "address": normalized.supplier.address,
                "metadata": {"created_from": "quotation_extraction"},
                "reliability": {"score": 0.5, "method": "rule_based", "sample_size": 0},
            },
        )

    async def _refresh_reliability(self, organization_id: str, supplier_id: str) -> None:
        supplier = await self.suppliers.get(organization_id, supplier_id)
        if supplier is None:
            return
        quotations = await self.quotations.list_filtered(
            organization_id, supplier_id=supplier_id, limit=100
        )
        reliability = compute_reliability(supplier, quotations=quotations)
        await self.suppliers.set_reliability(organization_id, supplier_id, reliability)

    @staticmethod
    def _confidence(processed, extraction, validation, normalized) -> dict[str, Any]:
        """A transparent confidence summary, not a black box number."""
        ocr = processed.ocr_confidence

        # Extraction confidence: how much of each item actually got filled in.
        if extraction.items:
            filled = 0
            total = 0
            for item in extraction.items:
                for value in (item.original_name, item.quantity, item.unit_price, item.total_price):
                    total += 1
                    if value is not None:
                        filled += 1
            extraction_confidence = round(filled / total, 4) if total else 0.0
        else:
            extraction_confidence = 0.0

        penalty = min(validation.error_count * 0.15 + validation.warning_count * 0.03, 0.6)
        normalization_confidence = round(max(0.0, 1.0 - penalty), 4)

        parts = [p for p in (ocr, extraction_confidence, normalization_confidence) if p is not None]
        overall = round(sum(parts) / len(parts), 4) if parts else None
        return {
            "extraction": extraction_confidence,
            "ocr": round(ocr, 4) if ocr is not None else None,
            "normalization": normalization_confidence,
            "overall": overall,
            "provider": extraction.provider,
        }


def _oid(value):
    from app.repositories.base import maybe_object_id

    return maybe_object_id(value)
