"""Assistant retrieval: hits come from the organization's own records, name their source, and an unrelated
question returns nothing instead of a guess."""
from app.services.agents.retrieval import build_chunks, search

QUOTES = [
    {"id": "q1", "supplier_name": "Maruti Traders", "effective_data": {
        "items": [{"original_name": "PVC pipe 2 inch", "quantity": 100, "unit": "Nos", "unit_price": 292.0}],
        "payment_terms": "30 days credit"}},
    {"id": "q2", "supplier_name": "Shree Plastics", "effective_data": {
        "items": [{"original_name": "MS plate 10mm", "quantity": 20, "unit": "Nos", "unit_price": 5400.0}],
        "payment_terms": "Advance payment"}},
]
EMAILS = [{"id": "c1", "kind": "negotiation", "status": "draft", "subject": "Better rate for MS plate",
           "body": "We would like a lower price on the MS plate 10mm and a 30 day credit period."}]


def test_a_question_finds_the_quotation_that_answers_it():
    hits = search(build_chunks(QUOTES, EMAILS), "who quoted pvc pipe")
    assert hits[0]["id"] == "q1" and hits[0]["kind"] == "quotation"
    assert "Maruti Traders" in hits[0]["excerpt"]


def test_emails_are_searchable_and_say_what_they_are():
    hits = search(build_chunks(QUOTES, EMAILS), "what did we ask about the MS plate price")
    assert "c1" in [h["id"] for h in hits]
    assert next(h for h in hits if h["id"] == "c1")["kind"] == "negotiation email (draft)"


def test_an_unrelated_question_returns_nothing():
    assert search(build_chunks(QUOTES, EMAILS), "weather in Mumbai tomorrow") == []


def test_empty_records_or_query_are_safe():
    assert search([], "pipe") == [] and search(build_chunks(QUOTES, EMAILS), "   ") == []
