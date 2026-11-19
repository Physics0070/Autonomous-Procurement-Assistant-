"""Grounding: figures not written in the document are flagged; figures that are written there are not.

Includes a small fault-injection eval on the five sample quotations: no false alarms on what the heuristic
reader really saw (regression), and a falsified figure is caught (capability).
"""
import asyncio
from pathlib import Path

import pytest

from app.schemas.extraction import AIExtractionResult
from app.services.documents.ai_extraction import heuristic_extraction
from app.services.documents.processor import process_document
from app.services.procurement.grounding import grounding_issues
from app.services.procurement.validation import validate_extraction

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
TEXT = "PVC PIPE 100 Nos x 292.00 = 29,200.00  Subtotal 29,200.00  GST 18% 5,256.00  Total 34,456.00 GSTIN 27AAAAA0000A1Z5"


def _ext(**kw):
    base = {"supplier": {"name": "Balaji Hardware", "gst_number": "27AAAAA0000A1Z5"},
            "items": [{"original_name": "PVC PIPE", "quantity": 100, "unit_price": 292.0, "total_price": 29200.0}],
            "commercials": {"subtotal": 29200.0, "tax_amount": 5256.0, "total_amount": 34456.0}}
    base.update(kw)
    return AIExtractionResult.model_validate(base)


def test_figures_written_in_the_document_pass():
    assert [i for i in grounding_issues(_ext(), TEXT) if i.code != "ungrounded_supplier_name"] == []


def test_an_invented_price_is_an_error_that_tells_the_model_what_to_do():
    ext = _ext(items=[{"original_name": "PVC PIPE", "quantity": 100, "unit_price": 310.0, "total_price": 31000.0}])
    codes = {i.code: i for i in grounding_issues(ext, TEXT)}
    assert codes["ungrounded_unit_price"].severity == "error"
    assert "Use only numbers written in the document" in codes["ungrounded_unit_price"].message


def test_a_total_that_is_just_quantity_times_price_is_not_invention():
    text = TEXT.replace("29,200.00  ", "")
    ext = _ext(commercials={})
    assert not [i for i in grounding_issues(ext, text) if "total_price" in i.code]


def test_a_part_of_an_ocr_glued_number_counts_as_read():
    # "100292" is OCR gluing 100 and 292: the corrected reading must not be called invention.
    ext = _ext(items=[{"original_name": "PVC PIPE", "quantity": 100, "unit_price": 292.0, "total_price": 29200.0}], commercials={})
    assert not [i for i in grounding_issues(ext, "PVC PIPE 100292 29,200.00") if i.code.startswith("ungrounded_q") or i.code == "ungrounded_unit_price"]


def test_validation_without_source_text_is_unchanged():
    assert not [i for i in validate_extraction(_ext()).issues if i.code.startswith("ungrounded")]


def test_a_hallucinated_gst_number_is_flagged():
    ext = _ext(supplier={"name": "Balaji Hardware", "gst_number": "29BBBBB1111B1Z9"})
    assert any(i.code == "ungrounded_gst" for i in grounding_issues(ext, TEXT))


def _sample_docs():
    for path in sorted(SAMPLES.glob("quotation_*")):
        doc = asyncio.run(process_document(path.read_bytes(), filename=path.name))
        yield path.name, doc


@pytest.mark.parametrize("name,doc", list(_sample_docs()), ids=lambda v: v if isinstance(v, str) else "")
def test_what_the_heuristic_reader_saw_has_no_false_alarms_and_a_falsified_price_is_caught(name, doc):
    ext = heuristic_extraction(doc)
    text = doc.text_for_ai(max_chars=10_000_000)
    amounts = [i for i in ext.items if i.unit_price]
    if not amounts:
        pytest.skip("heuristic reader found no priced line in this sample")
    assert [i for i in grounding_issues(ext, text) if i.code.startswith("ungrounded_") and "name" not in i.code] == [], name
    amounts[0].unit_price = round(amounts[0].unit_price * 1.37 + 0.13, 2)  # a plausible-looking invented price
    assert any(i.code == "ungrounded_unit_price" for i in grounding_issues(ext, text)), name


def test_a_total_worked_out_from_the_lines_plus_tax_is_arithmetic_not_invention():
    text = "PVC PIPE 100 Nos x 292.00 = 29,200.00 GST 18%"
    ext = _ext(commercials={"subtotal": 29200.0, "tax_percentage": 18.0, "total_amount": 34456.0})
    assert not [i for i in grounding_issues(ext, text) if i.field == "commercials.total_amount"]
