"""A line with a total but no quantity or rate is usually OCR having glued two numbers together
("100 292" read as "100292"). It must be an error, so the extraction agent re-reads once."""
from app.schemas.extraction import AIExtractionResult
from app.services.procurement.validation import Severity, validate_extraction


def _extraction(**item):
    return AIExtractionResult.model_validate({"supplier": {"name": "Balaji"}, "items": [{"original_name": "PVC PIPE", **item}]})


def test_a_total_without_quantity_and_rate_is_an_error_that_explains_how_to_fix_it():
    report = validate_extraction(_extraction(total_price=29200.0))
    issue = next(i for i in report.issues if i.code == "incomplete_item")
    assert issue.severity == Severity.ERROR
    assert "quantity x unit price" in issue.message and "merged" in issue.message


def test_a_complete_line_has_no_such_issue():
    report = validate_extraction(_extraction(quantity=100.0, unit_price=292.0, total_price=29200.0))
    assert not [i for i in report.issues if i.code == "incomplete_item"]


def test_a_line_with_nothing_priced_stays_a_warning():
    report = validate_extraction(_extraction(quantity=100.0))
    assert next(i for i in report.issues if i.code == "incomplete_item").severity == Severity.WARNING
