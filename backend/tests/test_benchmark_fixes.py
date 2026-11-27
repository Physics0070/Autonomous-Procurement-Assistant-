"""Fixes found with the 130-quotation benchmark: delivery time phrases, printed date styles, and preferring the page
image over OCR text for photos and scans."""
import pytest

from app.schemas.extraction import AIExtractionResult
from app.services.documents.second_reader import reconcile_readings
from app.services.procurement.normalizer_service import delivery_days_from_text
from app.services.procurement.validation import parse_date


@pytest.mark.parametrize("text,days", [("Immediate", 0), ("Ex-stock", 0), ("Ready stock", 0), ("4-6 weeks", 42), ("3 weeks", 21),
                                       ("Within 7 days", 7), ("10 working days from PO", 10), ("7-10 days", 10), ("2-3 weeks", 21),
                                       ("15 days", 15), (None, None), ("Ex-works Pune; transport by buyer", None)])
def test_delivery_time_phrases_become_the_longest_stated_days(text, days):
    assert delivery_days_from_text(text) == days


@pytest.mark.parametrize("text,iso", [("25-Oct-2026", "2026-10-25"), ("25-Oct-26", "2026-10-25"), ("29.09.2026", "2026-09-29"),
                                      ("30-09-26", "2026-09-30"), ("Dated 25th October 2026", "2026-10-25"),
                                      ("08 October 2026", "2026-10-08"), ("Date: 06/10/2026", "2026-10-06")])
def test_the_date_styles_indian_quotations_print_are_read(text, iso):
    assert parse_date(text).date().isoformat() == iso


def _reading(price, total=None):
    return AIExtractionResult.model_validate({"supplier": {"name": "Veltra"}, "items": [
        {"original_name": "Whiteboard marker black", "quantity": 100, "unit_price": price, "total_price": total if total is not None else 100 * price}]})


def test_for_a_photo_the_image_reading_is_kept_when_it_checks_out():
    text, image = _reading(30.8, total=3080.0), _reading(308.0)  # OCR text broke the price; its line total no longer adds up
    kept, notes, adopted = reconcile_readings(text, image, text_from_ocr=True)
    assert adopted and kept.items[0].unit_price == 308.0 and "page image" in notes[0]


def test_for_a_digital_pdf_the_text_reading_stays():
    kept, notes, adopted = reconcile_readings(_reading(308.0), _reading(30.8), text_from_ocr=False)
    assert not adopted and kept.items[0].unit_price == 308.0


def test_an_image_reading_that_checks_out_worse_is_not_preferred():
    text, image = _reading(308.0), _reading(30.8, total=99999.0)
    kept, _, adopted = reconcile_readings(text, image, text_from_ocr=True)
    assert not adopted and kept.items[0].unit_price == 308.0


class _Flaky:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def is_configured(self):
        return True

    async def read_image(self, prompt, images, system=None):
        from types import SimpleNamespace
        self.calls += 1
        return SimpleNamespace(ok=True, text=self.replies.pop(0), error=None)


def test_an_empty_page_image_reading_is_tried_once_more():
    import asyncio, json
    from app.services.documents.second_reader import second_read
    good = json.dumps({"supplier": {"name": "Veltra"}, "items": [{"original_name": "Marker", "quantity": 2, "unit_price": 10, "total_price": 20}]})
    flaky = _Flaky([json.dumps({"supplier": {"name": "Veltra"}, "items": []}), good])
    reading = asyncio.run(second_read([b"img"], provider=flaky))
    assert flaky.calls == 2 and reading.items[0].unit_price == 10


def test_a_good_page_image_reading_is_not_repeated():
    import asyncio, json
    from app.services.documents.second_reader import second_read
    good = json.dumps({"supplier": {"name": "Veltra"}, "items": [{"original_name": "Marker", "quantity": 2, "unit_price": 10, "total_price": 20}]})
    flaky = _Flaky([good, good])
    asyncio.run(second_read([b"img"], provider=flaky))
    assert flaky.calls == 1


def _priced(total, tax=18000.0):
    return AIExtractionResult.model_validate({"supplier": {"name": "Veltra"},
        "items": [{"original_name": "Generator", "quantity": 1, "unit_price": 100000, "total_price": 100000}],
        "commercials": {"subtotal": 100000, "tax_amount": tax, "total_amount": total}})


def test_a_suppliers_thousand_rupee_slip_is_sent_for_review():
    from app.services.procurement.validation import validate_extraction
    assert validate_extraction(_priced(119000.0)).requires_review      # printed 1,19,000; it adds up to 1,18,000
    assert not validate_extraction(_priced(118000.0)).requires_review  # adds up
    assert not validate_extraction(_priced(118001.0)).requires_review  # rounding is not a mistake


def test_a_price_that_includes_gst_is_not_a_mismatch():
    from app.services.procurement.validation import validate_extraction
    assert not validate_extraction(_priced(100000.0)).requires_review  # "GST included": total equals the subtotal
