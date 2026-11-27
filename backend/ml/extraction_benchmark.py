"""Field-level extraction benchmark on the 130 labelled quotations in ml/data/quotation_benchmark.

Runs the production reading path (text layer or OCR, AI extraction with one self-correction, second reader on page
images) on every document, maps the result onto the benchmark's ground-truth fields, and scores it.

Split: quotations are grouped by request (all 5 quotes of an RFQ stay together) and 30% of the requests are LOCKED.
Tuning looks only at the other 70%; the locked set is reported, never studied.

Usage (from backend/):  python -m ml.extraction_benchmark [--split tune|locked|all] [--fresh]
Predictions are cached in ml/artifacts/extraction_benchmark/ so a run can resume; --fresh re-reads everything.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

DATA = Path(__file__).resolve().parent / "data" / "quotation_benchmark"
OUT = Path(__file__).resolve().parent / "artifacts" / "extraction_benchmark"
REPORT = Path(__file__).resolve().parent / "artifacts" / "extraction_benchmark.md"
LOCKED_SHARE = 0.30


def _locked_requests() -> set[str]:
    """The 30% of requests (rounded) with the lowest hash of their id: stable, and blind to the content."""
    ids = sorted({row["rfq_id"] for row in csv.DictReader(open(DATA / "manifest.csv", encoding="utf-8"))},
                 key=lambda r: hashlib.sha1(r.encode()).hexdigest())
    return set(ids[: round(LOCKED_SHARE * len(ids))])


_LOCKED: set[str] = set()


def split_of(rfq_id: str) -> str:
    if not _LOCKED:
        _LOCKED.update(_locked_requests())
    return "locked" if rfq_id in _LOCKED else "tune"


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def same(truth: Any, predicted: Any) -> bool:
    """The benchmark's own rule: null must be matched by null; numbers within 0.5; text equal or contained once normalised."""
    if truth is None or predicted is None:
        return truth is None and predicted is None
    try:
        return abs(float(truth) - float(predicted)) <= 0.5
    except (TypeError, ValueError):
        pass
    a, b = _norm(truth), _norm(predicted)
    return a == b or (len(a) > 6 and (a in b or b in a))


def to_truth_shape(extraction) -> dict:
    """Our extraction contract mapped onto the benchmark's ground-truth keys."""
    from app.services.procurement.validation import parse_date

    q, c, s = extraction.quotation, extraction.commercials, extraction.supplier
    date = parse_date(q.date) if q.date else None
    valid_until = None
    if q.validity:
        parsed = parse_date(q.validity)
        days = re.search(r"(\d{1,3})\s*days?", q.validity, re.I)
        valid_until = parsed.date().isoformat() if parsed else (
            (date + timedelta(days=int(days.group(1)))).date().isoformat() if days and date else None)
    return {
        "supplier": {"name": s.name, "gstin": s.gst_number},
        "quotation_number": q.reference,
        "quotation_date": date.date().isoformat() if date else None,
        "valid_until": valid_until,
        "payment_terms": c.payment_terms,
        "delivery_days_max": _delivery(c),
        "freight": {"amount": c.transportation_cost},
        "subtotal": c.subtotal,
        "tax": {"total": c.tax_amount},
        "grand_total": c.total_amount,
        "items": [{"description": i.original_name, "quantity": i.quantity, "unit_price": i.unit_price, "amount": i.total_price}
                  for i in extraction.items],
    }


def _delivery(c):
    from app.services.procurement.normalizer_service import delivery_days_from_text

    parsed = delivery_days_from_text(getattr(c, "delivery_time", None))
    if parsed is None:
        parsed = delivery_days_from_text(c.delivery_terms)
    return parsed if parsed is not None else c.delivery_days


HEADER = {
    "supplier_name": lambda g: g["supplier"]["name"], "supplier_gstin": lambda g: g["supplier"]["gstin"],
    "quotation_number": lambda g: g["quotation_number"], "quotation_date": lambda g: g["quotation_date"],
    "valid_until": lambda g: g["valid_until"], "payment_terms": lambda g: g["payment_terms"],
    "delivery_days_max": lambda g: g["delivery_days_max"], "freight_amount": lambda g: g["freight"]["amount"],
    "subtotal": lambda g: g["subtotal"], "gst_total": lambda g: g["tax"]["total"], "grand_total": lambda g: g["grand_total"],
}
LINE = ("quantity", "unit_price", "amount")


def _get(f, g):
    try:
        return f(g)
    except (KeyError, TypeError):
        return None


def score_one(truth: dict, predicted: dict) -> dict:
    header = {k: same(f(truth), _get(f, predicted)) for k, f in HEADER.items()}
    invented = sum(1 for f in HEADER.values() if f(truth) is None and _get(f, predicted) is not None)
    pool = list(predicted.get("items") or [])
    lines = {k: [0, 0] for k in LINE}
    for item in truth["items"]:
        best = max(pool, key=lambda x: SequenceMatcher(None, _norm(item["description"]), _norm(x.get("description") or "")).ratio(), default=None)
        if best is not None:
            pool.remove(best)  # one predicted line answers one true line
        for k in LINE:
            lines[k][1] += 1
            lines[k][0] += bool(best) and same(item[k], best.get(k))
    return {"header": header, "lines": lines, "invented": invented, "extra_lines": len(pool)}


async def read_one(path: Path) -> dict:
    """The production reading path without the database. Both readings are kept, so the way they are combined can be
    changed and re-scored without calling any model again."""
    from app.services.documents.ai_extraction import extract_structured
    from app.services.documents.processor import process_document
    from app.services.documents.second_reader import page_images, pdf_has_images, second_read
    from app.services.procurement.validation import validate_extraction

    started = time.perf_counter()
    data = path.read_bytes()
    doc = await process_document(data, filename=path.name)
    extraction, error = await extract_structured(doc)
    source = doc.text_for_ai(max_chars=10_000_000)
    validation = validate_extraction(extraction, source)
    if not error and validation.error_count:
        complaints = chr(10).join(f"- {i.message}" for i in validation.issues if i.severity == "error")
        second, second_error = await extract_structured(doc, feedback=complaints)
        if not second_error and validate_extraction(second, source).error_count < validation.error_count:
            extraction = second
    image = None
    has_images = pdf_has_images(data)
    if (doc.ocr_used or has_images) and not error:
        reading = await second_read(page_images(data))
        image = reading.model_dump(mode="json", exclude={"raw_response"}) if reading else None
    return {"text": extraction.model_dump(mode="json", exclude={"raw_response"}), "image": image, "ocr": doc.ocr_used,
            "has_images": has_images, "ai_error": error, "seconds": round(time.perf_counter() - started, 2),
            "source_chars": len(source)}


def final_reading(saved: dict, policy: str = "production"):
    """How the two readings become one. "production" is what the app does (reconcile_readings)."""
    from app.schemas.extraction import AIExtractionResult
    from app.services.documents.second_reader import reconcile_readings
    from app.services.procurement.validation import validate_extraction

    text = AIExtractionResult.model_validate(saved["text"])
    if not saved.get("image"):
        return text
    image = AIExtractionResult.model_validate(saved["image"])
    if policy == "image_first" and saved.get("ocr"):
        # OCR text of photos and scans is the weak reading: keep the image reading unless it checks out worse.
        if validate_extraction(image).error_count <= validate_extraction(text).error_count:
            return image
    kept, _, _ = reconcile_readings(text, image, text_from_ocr=bool(saved.get("ocr")) and policy != "old")
    return kept


def summarize(rows: list[dict]) -> dict:
    header = defaultdict(lambda: [0, 0])
    lines = {k: [0, 0] for k in LINE}
    invented = extra = 0
    for r in rows:
        for k, ok in r["score"]["header"].items():
            header[k][0] += ok
            header[k][1] += 1
        for k, (a, b) in r["score"]["lines"].items():
            lines[k][0] += a
            lines[k][1] += b
        invented += r["score"]["invented"]
        extra += r["score"]["extra_lines"]
    h = sum(v[0] for v in header.values()), sum(v[1] for v in header.values())
    li = sum(v[0] for v in lines.values()), sum(v[1] for v in lines.values())
    return {"quotations": len(rows), "header": dict(header), "lines": lines, "header_acc": h[0] / max(h[1], 1),
            "line_acc": li[0] / max(li[1], 1), "all_acc": (h[0] + li[0]) / max(h[1] + li[1], 1), "fields": h[1] + li[1],
            "invented": invented, "extra_lines": extra}


async def main_async(split: str, fresh: bool, pace: float, policy: str = "production") -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = list(csv.DictReader(open(DATA / "manifest.csv", encoding="utf-8")))
    rows = []
    for m in manifest:
        part = split_of(m["rfq_id"])
        if split != "all" and part != split:
            continue
        cache = OUT / f"{m['quotation_id']}.json"
        saved = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() and not fresh else None
        if saved is None or "text" not in saved:
            saved = await read_one(DATA / m["file"])
            cache.write_text(json.dumps(saved, indent=1, default=str), encoding="utf-8")
            print(f"{m['quotation_id']} {m['format']:12s} {saved['seconds']:6.1f}s", flush=True)
            await asyncio.sleep(pace)
        from app.services.procurement.validation import validate_extraction

        final = final_reading(saved, policy)
        saved["needs_review"] = validate_extraction(final).requires_review
        saved["prediction"] = to_truth_shape(final)
        truth = json.loads((DATA / "ground_truth" / f"{m['quotation_id']}.json").read_text(encoding="utf-8"))
        rows.append({"id": m["quotation_id"], "format": m["format"], "quality": m["capture_quality"] or "n/a", "split": part,
                     "inconsistent": m["has_inconsistency"] == "1", "seconds": saved["seconds"],
                     "needs_review": saved.get("needs_review"), "score": score_one(truth, saved["prediction"])})
    return rows


def report(rows: list[dict]) -> str:
    def line(label, part):
        s = summarize(part)
        return (f"| {label} | {s['quotations']} | {100 * s['header_acc']:.1f}% | {100 * s['line_acc']:.1f}% | "
                f"**{100 * s['all_acc']:.1f}%** | {s['invented']} | {s['extra_lines']} |")

    groups = [("All", rows)] + [(f"Split: {p}", [r for r in rows if r["split"] == p]) for p in ("tune", "locked")]
    groups += [(f"Format: {f}", [r for r in rows if r["format"] == f]) for f in sorted({r["format"] for r in rows})]
    groups += [(f"Capture: {q}", [r for r in rows if r["quality"] == q]) for q in ("good", "medium", "poor")]
    table = "\n".join(line(label, part) for label, part in groups if part)
    s = summarize(rows)
    fields = "\n".join(f"| {k} | {a}/{b} | {100 * a / b:.1f}% |" for k, (a, b) in {**s["header"], **{f"line {k}": v for k, v in s["lines"].items()}}.items())
    flagged = [r for r in rows if r["inconsistent"]]
    caught = sum(1 for r in flagged if r["needs_review"])
    secs = sorted(r["seconds"] for r in rows)
    return f"""# Extraction benchmark: 130 labelled quotations

`python -m ml.extraction_benchmark` on `ml/data/quotation_benchmark` (synthetic documents generated by code, with a correct answer for
every field; see that folder's README). A field that is absent from the document is correct only if the extractor also
leaves it empty, so inventing a value counts as a miss. Requests are split 70% tune / 30% locked; the locked split is
never used to choose anything.

| Group | Quotations | Header fields | Line fields | All fields | Header values invented | Extra lines |
|---|---:|---:|---:|---:|---:|---:|
{table}

## By field (all quotations)

| Field | Right | Accuracy |
|---|---:|---:|
{fields}

Documents with a supplier's own arithmetic error: {len(flagged)}; flagged for review: {caught}.
Time per document: median {secs[len(secs) // 2]:.1f} s, slowest {secs[-1]:.1f} s.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["tune", "locked", "all"], default="all")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--pace", type=float, default=1.5, help="seconds between documents (free-tier rate limits)")
    parser.add_argument("--policy", choices=["production", "image_first", "old"], default="production")
    args = parser.parse_args()
    rows = asyncio.run(main_async(args.split, args.fresh, args.pace, args.policy))
    REPORT.write_text(report(rows), encoding="utf-8")
    for label, part in (("all", rows), ("tune", [r for r in rows if r["split"] == "tune"]), ("locked", [r for r in rows if r["split"] == "locked"])):
        if part:
            s = summarize(part)
            print(f"{label:6s} n={s['quotations']:3d} header {100 * s['header_acc']:.1f}% lines {100 * s['line_acc']:.1f}% all {100 * s['all_acc']:.1f}% invented {s['invented']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
