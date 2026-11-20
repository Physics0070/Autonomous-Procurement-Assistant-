"""Second reader: the image reading is compared with the text reading; disagreements on amounts are flagged,
nothing is changed, and a missing or failing vision vendor never breaks a quotation."""
from app.integrations.ai.base import AIProvider, AIResponse
from app.integrations.ai.fallback import FallbackProvider
from app.schemas.extraction import AIExtractionResult
from app.services.documents import second_reader
from app.services.documents.second_reader import compare_readings, page_images, second_read


def _reading(unit_price=292.0, total=29200.0, name="PVC pipe 2 inch"):
    return AIExtractionResult.model_validate({
        "items": [{"original_name": name, "quantity": 100, "unit_price": unit_price, "total_price": total}],
        "commercials": {"total_amount": total}})


def test_agreeing_readings_raise_nothing():
    assert compare_readings(_reading(), _reading(name="PVC PIPE 2 INCH")) == []


def test_a_different_price_is_flagged_with_both_values_and_the_text_reading_is_kept():
    text, image = _reading(unit_price=292.0, total=29200.0), _reading(unit_price=72.0, total=7200.0)
    issues = compare_readings(text, image)
    price = next(i for i in issues if i.field == "items.0.unit_price")
    assert (price.observed, price.expected, price.code) == (292.0, 72.0, "readers_disagree")
    assert "Check this value against the original" in price.message
    assert text.items[0].unit_price == 292.0  # never edited


def test_a_value_only_one_reader_gave_is_not_a_disagreement():
    image = AIExtractionResult.model_validate({"items": [{"original_name": "PVC pipe 2 inch", "quantity": 100}]})
    assert compare_readings(_reading(), image) == []


def test_items_that_do_not_match_by_name_are_not_compared():
    other = _reading(unit_price=1.0, total=100.0, name="Brass valve")
    assert not [i for i in compare_readings(_reading(), other) if i.field.startswith("items.")]


class _Blind(AIProvider):
    name, model = "blind", "m"

    def is_configured(self):
        return True

    def configuration_error(self):
        return None

    async def generate(self, prompt, **kw):
        return AIResponse(ok=True, text="{}")


class _Sees(_Blind):
    name = "sees"

    async def read_image(self, prompt, images, **kw):
        return AIResponse(ok=True, text='{"items": [{"original_name": "PVC pipe", "quantity": 100, "unit_price": 72, "total_price": 7200}]}')


async def test_a_blind_vendor_is_skipped_for_one_that_can_see():
    chain = FallbackProvider([_Blind(), _Sees()])
    reading = await second_read([b"img"], provider=chain)
    assert reading is not None and reading.items[0].unit_price == 72


async def test_no_vendor_that_can_see_gives_none_not_an_error():
    assert await second_read([b"img"], provider=FallbackProvider([_Blind()])) is None


async def test_pipeline_helper_returns_issues_and_the_stored_reading(monkeypatch):
    async def fake(images, provider=None):
        return _reading(unit_price=72.0, total=7200.0)

    monkeypatch.setattr(second_reader, "second_read", fake)
    monkeypatch.setattr(second_reader, "page_images", lambda data: [b"img"])
    sr = await second_reader.second_reading(b"x", _reading())
    assert sr.issues and sr.reading["items"][0]["unit_price"] == 72.0 and not sr.changed


async def test_the_switch_turns_it_off(monkeypatch):
    monkeypatch.setattr(second_reader.settings, "VISION_SECOND_READER", False)
    assert (await second_reader.second_reading(b"x", _reading())).reading is None


def test_page_images_ignores_files_it_cannot_show():
    assert page_images(b"PK\x03\x04 an excel file") == []
    assert page_images(bytes([255, 216, 255, 224]) + b"jpeg") != []


def test_names_the_ocr_spaced_differently_still_match():
    text = _reading(unit_price=292.0, name="PVCELBOW-2INCH")
    image = _reading(unit_price=72.0, total=7200.0, name="PVC ELBOW - 2 INCH")
    assert any(i.field == "items.0.unit_price" for i in compare_readings(text, image))


# ---- settling the clear-cut disagreements (found on real handwritten quotations) ----
from app.services.documents.second_reader import reconcile_readings  # noqa: E402


def _tanpure(total, line):
    return AIExtractionResult.model_validate({
        "items": [{"original_name": "10x10 Tent", "quantity": 6, "total_price": line}],
        "commercials": {"subtotal": line * 2 if line < 10000 else None, "total_amount": total}})


def test_a_slash_dash_read_as_a_digit_is_corrected_from_the_image():
    text, image = _tanpure(121541.0, 48001.0), _tanpure(12154.0, 4800.0)
    kept, notes, adopted = reconcile_readings(text, image)
    assert kept.items[0].total_price == 4800.0 and kept.commercials.total_amount == 12154.0 and not adopted
    assert notes and "extra digit" in notes[0]
    assert text.items[0].total_price == 48001.0  # the original reading is not touched


def test_a_genuine_difference_is_left_alone_for_a_person():
    text, image = _reading(unit_price=292.0, total=29200.0), _reading(unit_price=72.0, total=7200.0)
    kept, notes, adopted = reconcile_readings(text, image)
    assert kept.items[0].unit_price == 292.0 and notes == [] and not adopted


def test_when_the_text_found_no_items_the_image_reading_is_used_and_marked():
    empty = AIExtractionResult.model_validate({"supplier": {"name": "Trimurti"}})
    kept, notes, adopted = reconcile_readings(empty, _reading())
    assert adopted and kept.items and "Check it against the original" in kept.notes[-1]


def test_xls_workbooks_can_be_read():
    import xlrd  # the old Excel format needs this package; it was missing

    assert xlrd.__version__
