"""Stage test: raw bytes -> ProcessedDocument, for every supported format."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows consoles default to cp1252, which cannot print the multilingual samples.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services.documents.ocr import get_ocr_service  # noqa: E402
from app.services.documents.processor import process_document_sync  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def main() -> int:
    ocr = get_ocr_service()
    engine = ocr.select()
    print("=" * 78)
    print("OCR engines available :", ocr.available_engines() or "NONE")
    print("OCR engine selected   :", engine.name if engine else "NONE")
    print("=" * 78)

    files = sorted(SAMPLES.glob("*"))
    if not files:
        print("No sample files found. Run scripts/make_samples.py first.")
        return 1

    failures = 0
    for path in files:
        data = path.read_bytes()
        doc = process_document_sync(data, filename=path.name)
        ok = bool(doc.raw_text.strip() or doc.tables)
        status = "OK " if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"\n[{status}] {path.name}")
        print(f"       type={doc.document_type.value}  lang={doc.detected_language}  chars={len(doc.raw_text)}")
        print(f"       tables={len(doc.tables)}  pages={len(doc.pages)}  ocr_used={doc.ocr_used} "
              f"engine={doc.ocr_engine} conf={doc.ocr_confidence}")
        if doc.extraction_errors:
            print(f"       errors={doc.extraction_errors}")
        preview = doc.raw_text.strip().replace("\n", " / ")[:220]
        print(f"       text: {preview}")
        for t in doc.tables[:2]:
            print(f"       table '{t.name}': {t.row_count}r x {t.column_count}c headers={t.headers[:7]}")
            for row in t.rows[:2]:
                print(f"            {row[:7]}")

    print("\n" + "=" * 78)
    print(f"RESULT: {len(files) - failures}/{len(files)} documents produced usable output")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
