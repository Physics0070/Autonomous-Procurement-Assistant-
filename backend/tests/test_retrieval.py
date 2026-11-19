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


# ---- meaning-based search (a fake embedder: "pipe" and "tubing" point the same way) ----
import asyncio  # noqa: E402

from app.services.agents import retrieval  # noqa: E402
from app.services.agents.retrieval import asearch, price_rows, price_summary, similar_prices  # noqa: E402


class _FakeEmbedder:
    def __init__(self):
        self.calls = 0

    async def embed(self, texts):
        self.calls += 1

        def vec(t):
            t = t.lower()
            if "pipe" in t or "tubing" in t:
                return [1.0, 0.1, 0.0]
            if "plate" in t:
                return [0.0, 1.0, 0.0]
            return [0.0, 0.0, 1.0]

        return [vec(t) for t in texts]


def test_meaning_finds_a_word_the_records_never_use():
    retrieval._CACHE.clear()
    hits = asyncio.run(asearch(build_chunks(QUOTES, EMAILS), "who sells tubing", _FakeEmbedder()))
    assert hits and hits[0]["id"] == "q1"  # keyword search alone finds nothing for "tubing"
    assert search(build_chunks(QUOTES, EMAILS), "who sells tubing") == []


def test_if_embeddings_fail_keyword_search_still_answers():
    class Broken:
        async def embed(self, texts):
            return None

    retrieval._CACHE.clear()
    hits = asyncio.run(asearch(build_chunks(QUOTES, EMAILS), "pvc pipe", Broken()))
    assert hits[0]["id"] == "q1"


def test_embeddings_are_cached_between_questions():
    retrieval._CACHE.clear()
    embedder = _FakeEmbedder()
    chunks = build_chunks(QUOTES, EMAILS)
    asyncio.run(asearch(chunks, "pipe", embedder))
    first = embedder.calls
    asyncio.run(asearch(chunks, "pipe", embedder))
    assert embedder.calls == first  # the same chunks and the same query: no new calls


PAST = [
    {"id": "a", "supplier_id": "s1", "supplier_name": "Maruti Traders", "created_at": "2026-10-01T00:00:00",
     "effective_data": {"items": [{"original_name": "PVC PIPE-2INCH", "unit_price": 292.0}]}},
    {"id": "b", "supplier_id": "s2", "supplier_name": "Shree Plastics", "created_at": "2026-10-05T00:00:00",
     "effective_data": {"items": [{"original_name": "PVC pipe 2 inch", "unit_price": 310.0}]}},
    {"id": "c", "supplier_id": "s2", "supplier_name": "Shree Plastics", "created_at": "2026-10-06T00:00:00",
     "effective_data": {"items": [{"original_name": "MS plate 10mm", "unit_price": 5400.0}]}},
]


def test_past_prices_match_across_spelling_and_leave_unrelated_items_out():
    found = asyncio.run(similar_prices(price_rows(PAST), "PVC PIPE - 2 INCH"))
    assert {r["quotation_id"] for r in found} == {"a", "b"}


def test_the_current_quotation_is_not_compared_with_itself():
    found = asyncio.run(similar_prices(price_rows(PAST), "PVC PIPE 2 INCH", exclude_quotation="a"))
    assert [r["quotation_id"] for r in found] == ["b"]


def test_the_negotiation_summary_carries_no_supplier_names():
    found = asyncio.run(similar_prices(price_rows(PAST), "PVC PIPE 2 INCH"))
    summary = price_summary(found)
    assert summary == {"observations": 2, "lowest": 292.0, "median": 301.0, "highest": 310.0}
    assert "Maruti" not in str(summary) and "Shree" not in str(summary)
