# Release readiness

Status on 27 November 2026. Honest label: **demo-ready, not production-ready.** There are no outside users yet, a
quotation has not yet been imported from a real e-mail, and the AI runs on free tiers.

## How this round was planned

The engineering directive asked for 16 areas and 11 documents. Five independent reviewers (contrarian, first
principles, expansionist, outsider, executor) were asked which to do first; all five agreed:

1. Fix what had already caused a measured failure or could lose data.
2. Protect the credibility of the headline numbers (report the locked benchmark untouched, no tuning sweeps to hit a
   chosen target).
3. Write the rest down as limitations instead of producing paperwork that claims readiness the code does not have.

So this file replaces the separate audit, progress, technical-debt, security and deployment documents. The extraction
benchmark has its own file, [EXTRACTION_BENCHMARK.md](EXTRACTION_BENCHMARK.md); the earlier re-measured numbers are in
[VALIDATION_REPORT.md](VALIDATION_REPORT.md).

## Done this round, with tests

| Area | What was wrong | Change | Check |
|---|---|---|---|
| Extraction | Photos and scans read from OCR text: 84.9% of fields on the tune split | Page image read for photos and scans; clearer field definitions; dates such as "25-Oct-26"; delivery phrases; empty page-image reading retried once | Locked split, read once: **97.7%** (tune 98.2%); `tests/test_benchmark_fixes.py` |
| Arithmetic | 2% tolerance: 0 of 11 supplier arithmetic mistakes sent for review | ₹2 or 0.01% tolerance; a total that does not add up always needs review; GST-included totals accepted | 11 of 11 flagged; 20 of 119 correct quotations flagged (17 carry a discount) |
| Uploads | Whole file read into memory before the 25 MB check | Body refused by declared length before parsing (413); file read at most one byte past the limit | `tests/test_upload_limits.py` |
| Storage | Originals on local disk, which Render's free tier wipes on every deploy | `STORAGE_BACKEND=gridfs` keeps them in MongoDB; set in `render.yaml`; download served from either backend with a header-safe filename | `tests/test_gridfs_storage.py` (round trip, delete, other organization gets 404) |
| AI quota | No limit on concurrent model calls; parallel work spent the free quota and extraction fell from 98% to 93% | `AI_MAX_CONCURRENT_CALLS` (default 4) caps every outbound model call in the process; existing bounded retry on Retry-After and 30 s vendor cooldown kept | `tests/test_ai_concurrency.py` |
| Approvals | Any member could approve a paused agent run (purchase orders and e-mails already needed a manager) | Approving a run needs admin or procurement manager; anyone may still cancel | `tests/test_injection_boundaries.py` |
| Prompt injection | Boundaries existed but were untested | Tests: no tool a model can call approves, sends, issues, pays or deletes; tools not offered are refused (including dunder and private names); extra arguments such as another organization's id are dropped; members cannot approve | same file |
| Tests | The suite could reach real APIs (embeddings choose Gemini from its key alone), and one test passed only because a real key was in `.env` | Vendor keys blanked for every test run; fixture given a fake key | `tests/test_vendors.py` |

## Not done, and why

| Item | Decision |
|---|---|
| Model comparison for late-delivery risk (CatBoost, LightGBM, XGBoost, Optuna) to reach 0.85 | Deferred. 0.832 [0.815, 0.850] is time-split and calibrated. The weakness is inside shipment types (RDC 0.562), which is a data limitation; searching until a chosen score appears would be the metric inflation the directive forbids. |
| Per-field provenance (page, bounding box, method, correction history) | Deferred. The grounding check (every figure must appear in the document), the image second reader with flagged cells, and the original file shown beside the result cover the main risk. A schema-wide change is a separate piece of work. |
| Gmail and Drive end to end | The team signed in with Google. **Drive is verified** (a purchase order PDF was filed to their Drive). Gmail connects and syncs without errors, but the last sync found no messages, so importing a quotation from a real e-mail is **still to be shown**. |
| Per-user and per-organization AI rate limits, token budgets | Deferred until there is more than one real organization. The concurrency cap covers the measured failure. |
| Monitoring stack, frontend polish, separate docs for each area | Deferred; no users to justify them yet. |

## Known limits

* **Extraction:** measured on code-generated documents plus 16 real ones; scanned PDFs are the weakest format (89.6% on
  8 locked documents); handwriting 56 to 67% on 2 real documents.
* **Free tiers:** when quota runs out, reading falls back to weaker models and accuracy drops. Run one benchmark or
  batch at a time.
* **Discounts** are not extracted as a field, so a quotation with a discount is sent for review.
* **Late-delivery risk:** separates shipment types well, ranks within RDC shipments only slightly better than chance.
* **Storage:** GridFS has no lifecycle rules or backups beyond the database's own.
* **Security:** no per-user rate limiting on login or AI routes; JWT secret must be set per deployment; no antivirus
  scan of uploads (file type is checked from content and name).

## How to check

From `backend/`, MongoDB running:

```bash
pytest -q                                          # full suite
python -m ml.extraction_benchmark --split all      # rescore cached readings (no model calls)
python -m ml.validate_numbers                      # risk, price-error and forecast numbers with intervals
```

## Before calling it production-ready

1. One quotation e-mailed to the connected inbox and imported by a sync, written down.
2. 15 to 20 real supplier quotations hand-labelled and scored as an independent check.
3. Per-user rate limits on login and AI routes.
4. Backups for MongoDB (which now also holds the original files).
