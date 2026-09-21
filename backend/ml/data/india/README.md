# Indian reference data

| File | Source | What it is |
|---|---|---|
| `HSN_SAC.xlsx` | GST portal, `https://tutorial.gst.gov.in/downloads/HSN_SAC.xlsx` (downloaded 21 Sep 2026, 668,474 bytes) | Official HSN master: 21,935 goods codes with descriptions (sheet `HSN_MSTR`) and 681 service codes (`SAC_MSTR`). No GST rates. |
| `hsn_benchmark.csv` | Written for this project | 114 quotation-style item names with their 4-digit HSN heading, each checked against the official master; split into 29 dev / 85 test before any tuning. |

Known issue in the official file: heading 8539's own description is 8538's text; the detailed
rows beneath 8539 are correct.
