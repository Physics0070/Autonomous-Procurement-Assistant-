"""Active content is refused at the door; ordinary quotations pass untouched."""
import io
import zipfile
from pathlib import Path

import fitz
import pytest

from app.core.errors import ValidationError
from app.services.documents.safety import check_upload_safety

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _pdf(tamper=None) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Quotation  Steel pipe  10 Nos  450.00")
    if tamper:
        tamper(doc)
    return doc.tobytes()


def _zip(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in members.items():
            z.writestr(name, content)
    return buf.getvalue()


@pytest.mark.parametrize("path", sorted(p for p in SAMPLES.glob("*") if p.suffix.lower() in {".pdf", ".xlsx", ".xls", ".csv", ".png", ".jpg"}))
def test_the_sample_quotations_pass(path):
    check_upload_safety(path.read_bytes(), path.name)


def test_a_plain_pdf_passes():
    check_upload_safety(_pdf(), "q.pdf")


@pytest.mark.parametrize("name,tamper", [
    ("javascript", lambda d: d.xref_set_key(d.pdf_catalog(), "OpenAction", "<</S/JavaScript/JS(app.alert(1))>>")),
    ("escaped name", lambda d: d.xref_set_key(d.pdf_catalog(), "OpenAction", "<</S/J#61vaScript/JS(app.alert(1))>>")),
    ("launch", lambda d: d.xref_set_key(d.pdf_catalog(), "OpenAction", "<</S/Launch/F(cmd.exe)>>")),
    ("attachment", lambda d: d.embfile_add("payload.exe", b"MZ...")),
    ("rich media", lambda d: d.xref_set_key(d.pdf_catalog(), "OpenAction", "<</S/RichMedia>>")),
])
def test_a_pdf_with_active_content_is_refused(name, tamper):
    with pytest.raises(ValidationError, match="refused for safety"):
        check_upload_safety(_pdf(tamper), "q.pdf")


def test_excel_with_macros_is_refused():
    with pytest.raises(ValidationError, match="macros"):
        check_upload_safety(_zip({"[Content_Types].xml": "<Types/>", "xl/vbaProject.bin": b"\x00" * 10}), "q.xlsx")
    with pytest.raises(ValidationError, match="macro-enabled"):
        check_upload_safety(b"PK\x03\x04", "q.xlsm")
    with pytest.raises(ValidationError, match="macros"):
        check_upload_safety(b"\xd0\xcf\x11\xe0" + b"\x00" * 100 + "_VBA_PROJECT".encode("utf-16-le"), "q.xls")


def test_a_spreadsheet_that_unpacks_to_a_huge_size_is_refused(monkeypatch):
    from app.services.documents import safety

    monkeypatch.setattr(safety, "MAX_UNPACKED_BYTES", 1024 * 1024)
    with pytest.raises(ValidationError, match="unreasonable size"):
        check_upload_safety(_zip({"xl/worksheets/sheet1.xml": b"0" * (2 * 1024 * 1024)}), "q.xlsx")


async def test_the_upload_route_refuses_it_and_stores_nothing(api, org_a, db):
    bad = _pdf(lambda d: d.xref_set_key(d.pdf_catalog(), "OpenAction", "<</S/JavaScript/JS(app.alert(1))>>"))
    response = await api.post("/api/v1/documents/upload", headers=org_a["headers"], files={"file": ("q.pdf", bad, "application/pdf")})
    assert response.status_code in (400, 422) and "refused for safety" in response.text
    assert await db["quotations"].count_documents({}) == 0


def test_metadata_attachments_pass_but_payloads_do_not():
    check_upload_safety(_pdf(lambda d: d.embfile_add("Content Credentials", b"\x00\x00\x00 jumbc2pa")), "q.pdf")  # phone C2PA tag
    check_upload_safety(_pdf(lambda d: d.embfile_add("factur-x.xml", b"<?xml version='1.0'?><invoice/>")), "q.pdf")
    for name, payload in (("Content Credentials", b"MZ\x90\x00 disguised exe"), ("factur-x.xml", b"PK\x03\x04 a zip"),
                          ("notes.docx", b"plain text")):
        with pytest.raises(ValidationError, match="attached file"):
            check_upload_safety(_pdf(lambda d, n=name, b=payload: d.embfile_add(n, b)), "q.pdf")
