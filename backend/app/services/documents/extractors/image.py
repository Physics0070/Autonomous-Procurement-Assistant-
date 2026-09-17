"""Image extraction: always OCR, since there is no embedded text layer."""
from __future__ import annotations

from app.schemas.common import DocumentType, SourceType
from app.schemas.document import PageText, ProcessedDocument
from app.services.documents.detection import detect_language
from app.services.documents.ocr import get_ocr_service


def extract_image(
    data: bytes, filename: str = "", source_type: SourceType = SourceType.MANUAL_UPLOAD
) -> ProcessedDocument:
    doc = ProcessedDocument(source_type=source_type, document_type=DocumentType.IMAGE)
    doc.metadata["source_filename"] = filename

    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            doc.metadata.update({"width": img.width, "height": img.height, "image_mode": img.mode})
    except Exception as exc:
        doc.extraction_errors.append(f"Unable to read image metadata: {exc}")

    ocr = get_ocr_service()
    engine = ocr.select()
    if engine is None:
        doc.extraction_errors.append(
            "No OCR engine available. Install Tesseract (set TESSERACT_CMD) or rapidocr-onnxruntime."
        )
        doc.metadata["ocr_skipped_reason"] = "no_engine"
        return doc

    result = ocr.run(data, lang=None)
    if result.error:
        doc.extraction_errors.append(f"OCR failed: {result.error}")
        return doc

    doc.raw_text = result.text
    doc.ocr_used = True
    doc.ocr_engine = result.engine
    doc.ocr_confidence = result.confidence
    doc.detected_language = detect_language(result.text)
    doc.pages.append(
        PageText(
            page=1,
            text=result.text,
            char_count=len(result.text),
            method="ocr",
            ocr_confidence=result.confidence,
        )
    )
    doc.metadata["ocr_word_count"] = result.word_count
    return doc
