"""Stage test: ProcessedDocument -> validated AIExtractionResult."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.integrations.ai.factory import get_ai_provider  # noqa: E402
from app.services.documents.ai_extraction import extract_structured  # noqa: E402
from app.services.documents.processor import process_document_sync  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


async def main() -> int:
    provider = get_ai_provider()
    print("=" * 78)
    print("AI provider    :", provider.name)
    print("Configured     :", provider.is_configured())
    print("Config error   :", provider.configuration_error())
    print("=" * 78)

    for path in sorted(SAMPLES.glob("*")):
        doc = process_document_sync(path.read_bytes(), filename=path.name)
        result, error = await extract_structured(doc)
        print(f"\n--- {path.name} ---")
        print(f"  provider={result.provider} error={error}")
        s = result.supplier
        print(f"  supplier: name={s.name!r} gst={s.gst_number} email={s.email} phone={s.phone}")
        q = result.quotation
        print(f"  quotation: ref={q.reference} date={q.date} validity={q.validity} ccy={q.currency}")
        c = result.commercials
        print(f"  commercials: sub={c.subtotal} tax%={c.tax_percentage} taxamt={c.tax_amount} "
              f"freight={c.transportation_cost} total={c.total_amount}")
        print(f"               delivery_days={c.delivery_days} payment_days={c.payment_days} terms={c.payment_terms!r}")
        print(f"  items ({len(result.items)}):")
        for it in result.items:
            print(f"    - {it.original_name!r} qty={it.quantity} unit={it.unit} "
                  f"rate={it.unit_price} gst={it.gst_percentage} total={it.total_price}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
