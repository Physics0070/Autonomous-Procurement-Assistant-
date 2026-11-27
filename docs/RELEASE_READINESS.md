# Release readiness

Status on 28 November 2026. Assessment: **demo-ready; pilot-ready once the two open checks below pass; not
production-ready.** See the last section for the reasons.

This file covers what was hardened, what was deferred and why, and the known limits. The extraction benchmark has its
own file, [EXTRACTION_BENCHMARK.md](EXTRACTION_BENCHMARK.md); the re-measured model numbers are in
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
| Discounts | Not extracted, so a discounted quotation could not be reconciled and a purchase order missed the discount | Line and quotation discounts read as printed; checks, comparison and purchase orders use the price actually paid; the order takes a quotation discount off before GST | `tests/test_discounts.py` |
| Sign-in and AI limits | None | Sign-in locked after 10 failures per e-mail in 15 minutes (50 attempts per address); AI-backed routes limited to 10 requests per user per minute and 200 per organization per hour; in-process counts | `tests/test_rate_limits.py` |
| Upload content | Only the file type was checked | PDFs with scripts or launch actions refused; attached files refused unless they are metadata (Content Credentials, XML/JSON invoice data); macro-enabled or zip-bomb spreadsheets refused; all 38 of the team's real quotations pass | `tests/test_upload_safety.py` |
| Backups | None | `scripts/backup_db.py` backs up every collection (GridFS files included) and restores only into an empty database; restore of the development database (13 collections, 21,359 documents) identical by content hash | `tests/test_backup_restore.py` |
| Backup AI models | When the main model's free quota ran out, readings came from backup models without any sign (the tune split fell to 89.0% of fields on such a run) | A reading produced by a backup model is recorded as such and always sent for review | `tests/test_benchmark_fixes.py` |
| Tests | The suite could reach real APIs (embeddings choose Gemini from its key alone), and one test passed only because a real key was in `.env` | Vendor keys blanked for every test run; fixture given a fake key | `tests/test_vendors.py` |

## Not done, and why

| Item | Decision |
|---|---|
| Model comparison for late-delivery risk (CatBoost, LightGBM, XGBoost, Optuna) to reach 0.85 | Deferred. 0.832 [0.815, 0.850] is time-split and calibrated. The weakness is inside shipment types (RDC 0.562), which is a data limitation; searching until a chosen score appears would overfit the test period. |
| Per-field provenance (page, bounding box, method, correction history) | Deferred. The grounding check (every figure must appear in the document), the image second reader with flagged cells, and the original file shown beside the result cover the main risk. A schema-wide change is a separate piece of work. |
| Gmail and Drive end to end | The team signed in with Google. **Drive is verified** (a purchase order PDF was filed to their Drive). Gmail connects and syncs without errors, but the last sync found no messages, so importing a quotation from a real e-mail is **still to be shown**. |
| Scanned-PDF accuracy | Not attempted: every labelled scan has either been used for tuning or already read in the locked split, so an improvement could not be measured honestly. New labelled scans are needed. |
| Token budgets per organization | Deferred; request counts per user and organization are limited instead. |
| Monitoring stack, frontend polish, separate docs for each area | Deferred; no users to justify them yet. |

## Known limits

* **Extraction:** measured on code-generated documents plus 16 real ones; scanned PDFs are the weakest format (89.6% on
  8 locked documents); handwriting 56 to 67% on 2 real documents.
* **Free tiers:** when quota runs out, reading falls back to weaker models and accuracy drops. Run one benchmark or
  batch at a time.
* **Late-delivery risk:** separates shipment types well, ranks within RDC shipments only slightly better than chance.
* **Storage and backups:** GridFS has no lifecycle rules; backups run only when `scripts/backup_db.py` is scheduled, and must be copied off the machine.
* **Security:** request limits are kept in one process's memory (several server instances would each count separately);
  JWT secret must be set per deployment; uploads get content checks, not an antivirus scan.

## Files from untrusted senders

Every file, uploaded or collected from Gmail, passes the same path:

1. Size is checked before the file is held in memory (25 MB).
2. The type is decided from the file's content, not its name.
3. Active content is refused before anything is stored: PDF scripts and launch actions, attached executables, archives
   or Office files, macro-enabled spreadsheets, and spreadsheets that unpack to an unreasonable size.
4. Files are only ever read as data (PyMuPDF renders, openpyxl and xlrd read cell values, Pillow decodes images); no
   macro, script or attachment is run.
5. Extracted figures are held as "needs checking" until a person accepts them when anything does not add up, and no
   purchase order or e-mail leaves without an approver.

There is no antivirus scan. Where the app accepts files from people outside the organization, run it on a host with
ClamAV (about 1 GB of memory, more than the free hosting tier offers) and scan the stored originals, or limit Gmail
collection to known suppliers with `GMAIL_SYNC_QUERY` (a Gmail search, e.g. `has:attachment from:(sales@a.in OR quotes@b.in)`).

## How to check

From `backend/`, MongoDB running:

```bash
pytest -q                                          # full suite
python -m ml.extraction_benchmark --split all      # rescore cached readings (no model calls)
python -m ml.validate_numbers                      # risk, price-error and forecast numbers with intervals
```

## Assessment

| Level | Verdict | Why |
|---|---|---|
| Demo-ready | **Yes** | Every main flow works end to end on the sample and real quotations; backend suite 8,490 passed, 60 skipped, 0 failed (28 Nov); frontend type-check clean and production build succeeds. |
| Pilot-ready (one friendly small business, supervised) | **After two checks** | (1) one quotation e-mailed to the connected inbox and imported by a sync; (2) a re-read of the tune split with the main model to confirm the discount fields did not lower accuracy. |
| Production-ready | **No** | Free AI tiers whose quota runs out within a day of heavy use; real-document accuracy rests on 16 quotations not labelled independently; request limits and storage are single-instance; no scheduled off-site backups; no antivirus. |

Before production: a paid or higher-quota AI plan, 15 to 20 real quotations labelled by the team and scored, a daily
backup scheduled and copied off the machine, and limits moved to a shared store if more than one server runs.
