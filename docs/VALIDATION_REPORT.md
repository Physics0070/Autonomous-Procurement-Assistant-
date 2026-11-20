# Validation report: the project's numbers, re-measured

20 November 2026. Every figure below was re-measured on this laptop (16-thread CPU, MongoDB local, free-tier AI keys). Intervals are
95% bootstrap (2,000 resamples) or Wilson intervals. **Team-supplied** data (the HSN list, the 4,000 orders and the price files) is described by the team as real vendor data; I have not
verified its source independently, and it is labelled wherever it is used.

## 1. The numbers to quote

| Claim | Verified value | Data | Verdict |
|---|---|---|---|
| Late-delivery risk, ROC-AUC | **0.832** [0.815, 0.850] vs 0.761 [0.740, 0.780] for the supplier's own record; gain +0.071 [0.054, 0.090], positive in 100% of resamples | Real: USAID SCMS, 2,545 later shipments | **Holds.** Quote with the interval. |
| ... caution | Within each shipment type the model is weak: external vendors 0.808 (1,550 shipments, only 2.5% late), **RDC shipments 0.562** (995 shipments, 32% late) | same | Much of the 0.832 comes from telling the two shipment types apart. Say so if asked. |
| ... calibration | Expected calibration error 0.030; Brier 0.0985 | same | Holds. |
| Catches late deliveries | Shipped threshold: flags 21.7% of orders, precision 0.358 [0.320, 0.397], recall 0.553 [0.503, 0.604]. Screening threshold: flags 40.8%, precision 0.317, recall **0.924** [0.896, 0.951] | same | Holds. |
| HSN heading accuracy (with model) | **98.8%** [93.6, 99.8] on the 85 original held-out items (reproduced today); **91.2%** [87.0, 94.1] on 250 items from the broader labelled set (94.0% on the first 100, 89.3% on 150 fresh) | benchmark: hand-checked; broad set: team-supplied | **The 94% I quoted earlier was optimistic.** Use 91% for general goods and 98.8% for the easy benchmark. |
| HSN text matching alone | 27.6% top-1 on 750 items (shortlist of 30 contains the answer 79.6%) | team-supplied | Holds. |
| HSN with no model | 53% (closest labelled item) | team-supplied | Holds. |
| Extraction, fields correct | **96.6 to 96.9%** (282 of 291 fields) over three runs on 16 real documents; typed photos 98.0% (4 docs), digital PDFs 97.8% (10 docs), **handwritten 56 to 67% (2 docs)** | Real documents; answers read by me | Holds for typed documents. Handwriting is weak and the sample is tiny. Run-to-run variation is about 2 fields. |
| Price errors caught | Later 150 quotes: any flag precision **0.75** [0.63, 0.86], recall **1.00**; HIGH-only precision 0.83 [0.71, 0.94], recall 0.90 [0.79, 0.98]. 10.3% of correct quotes flagged. | Team-supplied labels | Holds on this file only. Reliable at 20% or more off the item's usual price; 0 of 2 below 10% off, 2 of 4 at 10 to 20%. |
| Forecast error (sMAPE) | **About 55 for both product groups** (ARV 55.8, HRDT 55.0; five cut-off months each) | Real SCMS | **Weak.** Present as a trend aid. My earlier "HRDT 66.9 to 53.6" did not hold at other cut-offs and is withdrawn. |
| GSTIN check digit | 4 of 4 GSTINs from real quotations and the published sample pass; every one-character corruption fails (300 generated cases) | Real | Holds. |
| Automated tests | **8,117 pass, 60 skipped** (277 hand-written + 7,900 generated stress cases) | n/a | Holds. |

## 2. Latency (client wall-clock over 127.0.0.1, demo organization of 9 quotations)

| Operation | p50 | p95 | Notes |
|---|---:|---:|---|
| Login | 0.45 s | 0.46 s | Password hashing; deliberately slow |
| Read endpoints (dashboard, quotations, detail, suppliers, requests, orders, emails, comparison) | 8 to 21 ms | under 30 ms | 30 calls each, no errors |
| Reports (spend, forecast, models) | 7 to 12 ms | under 15 ms | Cached; a first load on the 10,324-order organization took about 2 s when last measured (not re-measured) |
| 20 users on the dashboard at once | 0.23 s | 0.27 s | 77 requests per second, 0 errors in 100 |
| HSN suggestion (model) | 1.4 s | 9.0 s | The slow tail is Gemini retries |
| Assistant answer (model plus tools) | 1.7 s | 3.9 s | 6 questions |
| Embedding call (3 texts) | 0.56 s | 0.62 s | |
| Short model call | 0.37 s | 0.67 s | |
| Reading a typed PDF with a text layer, start to finish | 6.6 s | 14.4 s | Mostly the model call |
| Reading a typed phone photo | **29.7 s** | 38.7 s | OCR 19.8 s of it. Was 53 s before limiting the OCR threads (see section 4). |
| Reading a handwritten photo | 17.5 s | 19.7 s | was 31 s |

Installing Tesseract (not installed here) would cut the photo time further; the app picks it automatically.

## 3. How hard the tests are

* **7,900 generated cases**, each from a seed so a failure names its seed: 2,300 validation and grounding cases (clean quotations raise
  nothing; inflated prices, changed totals, invented prices, invented GST numbers and dropped lines are each caught), 1,500
  second-reader cases (an extra trailing digit is always corrected; a genuine difference is never changed), 700 price-detector
  cases, 1,000 GST cases, 1,400 parsing cases (garbage never raises), 700 ranking cases (cheapest ranks first; scaling every price
  keeps the order; scores stay within 0 to 1), 200 search cases, 200 forecast cases.
* **Known, tested limits:** a missing line item under 3% of the subtotal is within the 2% rounding tolerance and goes unflagged; 60
  cases skip for that reason or because the quotation had a single line.
* **Real-document tests:** 16 documents read by me, including a quotation whose text layer disagrees with what the page shows.

## 4. Faults found while validating (all fixed and pushed)

| Fault | How it was found | Fix |
|---|---|---|
| Forecast crashed on series of about 12 to 20 months | Stress tests (24 of 200 cases failed) | Seasonal backtests need a full year of history |
| "Pick the best backtest" forecast lost to the plain linear trend | Five cut-off months | Another method must beat the linear trend by 25% |
| A quotation with a missing quantity or price could pass as fine | Real keychain quotation | Any incomplete line now needs a person |
| A PDF whose page image shows different figures from its text layer was trusted | Same quotation | PDFs that carry page images are also read as images |
| A misread or invented GST number looked valid | Design review | Check digit verified against real GSTINs |
| Photos took 53 s to read | Latency run | OCR on 4 threads with larger batches: 16 s instead of 38 s, same 102 text boxes |
| 94% HSN figure was optimistic | 150 fresh items | Reported as 91% (broad) and 98.8% (easy) |

## 5. What not to claim

* Results on the team-supplied files (price errors, broad HSN set, order features) as proven field accuracy until their source is documented in the report.
* The risk model as accurate within shipment types; it separates types well and ranks RDC shipments only slightly better than chance.
* A forecast better than about 55% error.
* Handwriting reading as reliable: two documents, 56 to 67%.
* OCR accuracy beyond these 16 documents; most are typed.

Reproduce: `python -m ml.validate_numbers` (risk, price, forecast), `python scripts/measure_latency.py --ai` (API), `pytest` (all tests).
Raw results: `backend/ml/artifacts/validation_numbers.json`, `latency.json`.
