"""Generate realistic, deliberately inconsistent sample quotations.

Three suppliers quote the same requirement in three different formats, with
different wording, different units and different completeness - which is the
actual problem this system exists to solve.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
SAMPLES.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# 1. Digital PDF - Shree Plastics
# --------------------------------------------------------------------------
def make_digital_pdf() -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    lines = [
        ("SHREE PLASTICS & PIPES PVT LTD", 16, True),
        ("Plot 42, MIDC Industrial Area, Pune - 411018, Maharashtra", 9, False),
        ("GSTIN: 27AABCS1429B1ZQ   |   Phone: +91 98220 41556", 9, False),
        ("Email: sales@shreeplastics.co.in", 9, False),
        ("", 9, False),
        ("QUOTATION", 14, True),
        ("Quotation No: SP/2026/0417        Date: 12/08/2026", 10, False),
        ("Valid for: 30 days from date of issue", 10, False),
        ("", 9, False),
        ("Sr  Description                          Qty    Unit   Rate      GST%   Amount", 9, True),
        ("--------------------------------------------------------------------------", 9, False),
        ("1   PVC Pipe 2 inch (Class-2, 6m)        100    Nos    285.00    18     28500.00", 9, False),
        ("2   PVC Elbow 2 inch                      40    Nos     48.50    18      1940.00", 9, False),
        ("3   Solvent Cement 500ml                   10    Btl    310.00    18      3100.00", 9, False),
        ("--------------------------------------------------------------------------", 9, False),
        ("                                          Sub Total              33540.00", 9, False),
        ("                                          GST @ 18%               6037.20", 9, False),
        ("                                          Transportation          1200.00", 9, False),
        ("                                          GRAND TOTAL            40777.20", 9, True),
        ("", 9, False),
        ("Delivery: Within 7 days from confirmed purchase order.", 10, False),
        ("Payment Terms: 30 days from date of invoice.", 10, False),
        ("Warranty: 12 months against manufacturing defects.", 10, False),
        ("", 9, False),
        ("For SHREE PLASTICS & PIPES PVT LTD", 9, False),
        ("Authorised Signatory", 9, False),
    ]
    y = 60
    for text, size, bold in lines:
        if text:
            page.insert_text(
                (50, y), text, fontsize=size, fontname="hebo" if bold else "helv"
            )
        y += size + 6
    path = SAMPLES / "quotation_shree_plastics.pdf"
    doc.save(str(path))
    doc.close()
    return path


# --------------------------------------------------------------------------
# 2. Excel - Maruti Traders (different column names, different units)
# --------------------------------------------------------------------------
def make_excel() -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Quote"

    ws["A1"] = "MARUTI TRADERS"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Shop 7, Gandhi Market, Nashik - 422001"
    ws["A3"] = "GST No: 27AAGCM4455K1Z8"
    ws["A4"] = "Contact: 0253-2456789 / info@marutitraders.in"
    ws["A6"] = "Quotation Ref"
    ws["B6"] = "MT-QT-2026-88"
    ws["A7"] = "Dated"
    ws["B7"] = "14-08-2026"
    ws["A8"] = "Validity"
    ws["B8"] = "15 days"

    headers = ["S.No", "Material Description", "Units", "UOM", "Price/Unit (INR)", "Tax %", "Line Total"]
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=10, column=col, value=header)
        cell.font = Font(bold=True)

    rows = [
        [1, '2" PVC PIPE CLASS 2', 100, "PCS", 279.0, 18, 27900.0],
        [2, 'PVC ELBOW 2"', 40, "PCS", 52.0, 18, 2080.0],
        [3, "SOLVENT CEMENT (500 ML)", 10, "BOTTLE", 295.0, 18, 2950.0],
        [4, "TEFLON TAPE", 25, "PCS", 12.0, 18, 300.0],
    ]
    for r, row in enumerate(rows, start=11):
        for c, value in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=value)

    ws["F16"] = "Basic Amount"
    ws["G16"] = 33230.0
    ws["F17"] = "GST 18%"
    ws["G17"] = 5981.4
    ws["F18"] = "Freight"
    ws["G18"] = 0
    ws["F19"] = "Net Payable"
    ws["G19"] = 39211.4
    ws["F19"].font = Font(bold=True)

    ws["A21"] = "Delivery: 10-12 working days ex-godown"
    ws["A22"] = "Payment: 50% advance, balance against delivery"
    ws["A23"] = "Freight: Included, delivered to site"

    path = SAMPLES / "quotation_maruti_traders.xlsx"
    wb.save(str(path))
    return path


# --------------------------------------------------------------------------
# 3. Image (PNG) - Balaji Hardware, handwritten-ish / scanned style
# --------------------------------------------------------------------------
def _render_text_image(lines, width=1000, line_height=34, font_size=22, margin=40):
    from PIL import Image, ImageDraw, ImageFont

    height = margin * 2 + line_height * len(lines)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font = None
    bold_font = None
    for candidate in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(candidate):
            font = ImageFont.truetype(candidate, font_size)
            break
    for candidate in (
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(candidate):
            bold_font = ImageFont.truetype(candidate, font_size + 4)
            break
    if font is None:
        font = ImageFont.load_default()
    if bold_font is None:
        bold_font = font

    y = margin
    for text, bold in lines:
        draw.text((margin, y), text, fill="black", font=bold_font if bold else font)
        y += line_height
    return img


def make_image() -> Path:
    lines = [
        ("BALAJI HARDWARE STORES", True),
        ("Main Road, Satara - 415001", False),
        ("Ph: 9822551144   GSTIN: 27AAKFB9911L1ZR", False),
        ("", False),
        ("QUOTATION No BH-221    Date: 16/08/2026", True),
        ("", False),
        ("Item                          Qty   Rate    Amount", True),
        ("PVC PIPE - 2 INCH             100   292     29200", False),
        ("PVC ELBOW - 2 INCH             40    45      1800", False),
        ("SOLVENT CEMENT 500ML           10   305      3050", False),
        ("", False),
        ("Sub Total                            34050", False),
        ("GST 18 percent                        6129", False),
        ("Total Amount                         40179", True),
        ("", False),
        ("Delivery within 5 days", False),
        ("Payment 15 days credit", False),
    ]
    img = _render_text_image(lines)
    path = SAMPLES / "quotation_balaji_hardware.png"
    img.save(str(path))
    return path


# --------------------------------------------------------------------------
# 4. Scanned PDF - the image above wrapped in a PDF with no text layer
# --------------------------------------------------------------------------
def make_scanned_pdf() -> Path:
    import fitz

    png = SAMPLES / "quotation_balaji_hardware.png"
    if not png.exists():
        make_image()
    doc = fitz.open()
    img_doc = fitz.open(str(png))
    rect = img_doc[0].rect
    pdf_bytes = img_doc.convert_to_pdf()
    img_doc.close()
    img_pdf = fitz.open("pdf", pdf_bytes)
    page = doc.new_page(width=rect.width, height=rect.height)
    page.show_pdf_page(page.rect, img_pdf, 0)
    path = SAMPLES / "quotation_balaji_scanned.pdf"
    doc.save(str(path))
    doc.close()
    img_pdf.close()
    return path


# --------------------------------------------------------------------------
# 5. Multilingual PDF - Hindi/English mixed, incomplete data
# --------------------------------------------------------------------------
def make_multilingual_pdf() -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "NEW BHARAT PIPE UDYOG",
        "Kanpur, Uttar Pradesh - 208001",
        "Mob: 9415778822",
        "",
        "QUOTATION / भाव पत्र",
        "Date: 18/08/2026",
        "",
        "Item                                 Qty     Rate",
        "PVC पाइप 2 इंच                        100     271",
        "PVC Elbow 2 inch                      40      44",
        "Solvent Cement 500 ml                 10      288",
        "",
        "Total (approx)                              32000",
        "GST extra as applicable",
        "Delivery: 15-20 days",
    ]
    # A Devanagari-capable font is required, otherwise the base-14 fonts emit
    # replacement glyphs and the "multilingual" sample is not multilingual.
    devanagari_font = None
    for candidate in (r"C:\Windows\Fonts\mangal.ttf", r"C:\Windows\Fonts\Nirmala.ttc"):
        if os.path.exists(candidate):
            devanagari_font = candidate
            break

    fontname = "helv"
    if devanagari_font:
        page.insert_font(fontname="deva", fontfile=devanagari_font)
        fontname = "deva"

    y = 60
    for text in lines:
        if text:
            page.insert_text((50, y), text, fontsize=11, fontname=fontname)
        y += 20
    path = SAMPLES / "quotation_new_bharat.pdf"
    doc.save(str(path))
    doc.close()
    return path


if __name__ == "__main__":
    outputs = [
        make_digital_pdf(),
        make_excel(),
        make_image(),
        make_scanned_pdf(),
        make_multilingual_pdf(),
    ]
    for path in outputs:
        print(f"{path.name:42s} {path.stat().st_size:>8,} bytes")
