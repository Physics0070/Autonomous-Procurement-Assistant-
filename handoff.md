# Handoff — 28 Nov 2026

## 1. Project
Autonomous Procurement Assistant, VIT Pune SY-K10 (Vishwajeet Surve, Soham Joshi, Soham Mote, Atharva Sonje; guide
Prashant L. Mandale). Repo `Physics0070/Autonomous-Procurement-Assistant-`, single branch `main`, last commit
`89e7d86`, pushed. Progress table: `CHECKLIST.md`. Readiness verdict: `docs/RELEASE_READINESS.md`.

Stack: FastAPI + MongoDB (Motor) backend, React/TypeScript/Vite frontend. AI extraction chain
`gemini-3.1-flash-lite → groq gpt-oss-20b → nvidia nemotron` through `FallbackProvider` (free tiers).

## 2. Current state (verified 28 Nov)
| Check | Result |
|---|---|
| Backend `pytest -q` (from `backend/`, run alone) | **8,537 passed, 60 skipped, 0 failed** (~12 min) |
| Frontend `npx tsc --noEmit -p .` / `npx vite build` | clean / builds |
| Last change after the full run | scorecard `VERSION = 3`; the two scorecard test files pass (47) |

Assessment: **demo-ready yes; pilot-ready after two checks (below); production-ready no.**

## 3. What was done in this session (commits, oldest first)
| Commit | What |
|---|---|
| `fdf7989` | Extraction benchmark (130 code-generated quotations, 90 tune / 40 locked), review flags for supplier arithmetic, upload/storage/AI-quota hardening |
| `8a64b1e` | Discounts end to end, sign-in and AI request limits, upload content checks, GridFS storage, backup and restore script |
| `96514de` | Readings from backup AI models always flagged for review; README separates real (16) and generated numbers; readiness assessment |
| `bced692` | Supplier performance scorecard replaced the old reliability score (profile completeness and our own reading errors no longer count against a supplier); receipt at delivery; who cancelled |
| `ebb602d` | Scoring audit (13 findings): receipt-based OTIF, quantity-weighted rejections, accepted quantity, provisional/coverage, weights that add up, email-time responsiveness, invoice classes, receipt line validation, no cross-currency pricing, GST basis from reconciling figures, reading errors never scored, high-anomaly review gate with confirmed award, weight validation |
| `89e7d86` | Follow-up (test first, 18 of 20 failing before): per-round RFQ timing, zero invoices, neutral score for single/tied quotations, GST wording ("inclusive of GST", "GST extra"), PO: GST out of inclusive rates, percentage vs fixed discounts, changed-quantity warning, paisa reconciliation, invalid values blocked. Report: `docs/SCORING_FIX_VERIFICATION.md` |

## 4. Supplier scorecard (how "risky" is decided now)
`backend/app/services/procurement/reliability.py`, rule-based, from the organization's own records only:
on-time in full 30% · quality 30% · fulfilment 15% · commercial 15% · responsiveness 10%.
* Fewer than 3 assessed orders → **New supplier** (no score; neutral 0.5 in the ranking).
* Under 5 orders or 60% of the weight backed by records → **provisional**; moves the ranking only part way from neutral.
* Badges: Good ≥ 75 · OK 50–74 · Needs attention < 50. Each factor's scaled weight and points are shown and add up.
* Delivery date is automatic; **received/rejected quantities, invoice amount/type and who cancelled must be recorded
  by a person** on the Purchase orders page. Until that happens most suppliers stay New or provisional — expected.
* The ML late-delivery model is separate, shown beside it.

## 5. Numbers (from `docs/FINAL_REPORT.md`, `docs/EXTRACTION_BENCHMARK.md`)
| Component | Result |
|---|---|
| Late-delivery risk (random forest, SCMS, time split) | ROC-AUC 0.832 [0.815, 0.850]; baseline 0.761; Brier 0.0985; RDC shipments only 0.562 |
| Price-error detector (later 150 quotes) | precision 0.75 / recall 1.00; HIGH only 0.83 / 0.90; 10.3% false flags |
| Demand forecast (Croston, SCMS) | error 21–55% by series; range covered 75–78% |
| HSN suggestion | 98.8% (85 held out), 91.2% (250 items) |
| Extraction, 16 real quotations | 96.6–96.9% of fields; handwriting 56–67% |
| Extraction, 40 locked generated quotations | 97.7% (scanned PDF 89.6%) |
| Same, on backup models after Gemini quota ran out | 89.0% (tune split; cause not fully separated from the new discount fields) |

Datasets: USAID SCMS (10,324 shipments), GST HSN master (21,935), HSN benchmark (114) and labelled set (750), team
order file (4,000), team price file (468 + 300 labelled), 16 real quotations (private), 130 generated quotations.
Team-supplied files are not independently verified. Rejected this session as unsuitable: tender DB mirror, ICAI
vendor payments (fictional), Kaggle "vendor performance" (fictional liquor retail), DataCo (label leakage), old WPI
2004 series. Optional later: WPI 2011-12 series for a price-rise check; SROIE receipts as a second real-document test.

## 6. Open items
**Needed before a pilot**
1. **Gmail import end to end** — waiting on the team: send one quotation PDF as an attachment from another address
   to the connected inbox, then sync. Drive filing is already verified.
2. **Gemini re-read of the 90 tune quotations** with the discount fields, after the daily free quota resets:
   back up `backend/ml/artifacts/extraction_benchmark/` first, run
   `python -m ml.extraction_benchmark --split tune --fresh --pace 8` alone. Never re-read the locked split.

**Recommended next**
3. **Review flag is too strict:** 61 of 74 dev quotations (82%) need review, mostly "line missing a line total"
   when quantity and rate are present. Accepting computable lines would cut it to ~27%. Not done — awaiting go-ahead.
   Also drop item "lines" with no quantity, rate or amount (headings/notes).
4. Reprocess the 74 dev quotations with the current pipeline (costs AI quota; corrections are kept).
5. Label 15–20 real quotations (team, ~2 h; files in `D:\SOHAM ALL\EDC Finance\EAD ALL`, 22 distinct). The same folder
   has 4 comparative sheets and 2 real POs: compare the app's pick and PO with the team's — best real-world check.
6. Show `discount_type` on the PO page; recompute saved comparisons (they keep old labels until recomputed).

**Before production:** paid/higher AI quota, scheduled off-machine backups (`scripts/backup_db.py`), shared store for
rate limits if more than one server, antivirus or sender filter (`GMAIL_SYNC_QUERY`), real scorecard validation from
pilot deliveries.

## 7. Running it
* MongoDB on 27018 (dies sometimes): `/c/mongo-bin/mongod-x64-win32-7.0.14.exe --dbpath C:/mongo-data/db --port 27018 --bind_ip 127.0.0.1`
* Backend and frontend: `.claude/launch.json` (`backend` on 8000, `frontend` on 5173). Restart the backend after
  backend changes (no reload); startup rescores suppliers on an older scorecard version.
* Backup/restore check: `python scripts/backup_db.py backup|restore|verify` (restore only into an empty database).

## 8. Gotchas
* **Never run two pytest processes at once** — they share `procurement_assistant_test` and drop it per test (gives
  false `KeyError` setup errors).
* Free AI quota: run one benchmark or batch at a time; readings from backup models are flagged for review.
* `conftest.py` blanks vendor keys and lifts rate limits; tests never call real APIs.
* Shell heredocs mangle nested quotes; put patch scripts in the scratchpad and run them with Python.

## 9. Standing rules from the team
* Never commit or push without being asked; never print or commit secrets (`backend/.env` is untracked).
* Never commit Word documents, root PDFs, CSVs or `quotation_dataset.zip`.
* The demo login stays local, never in the repo. Ask before downloading models or datasets.
* No synthetic data to inflate metrics; report real and generated numbers separately; no fabricated results.
* Do not add agents, LLM providers or microservices; do not build ProcureSim; never send real emails or POs in tests.
* Keep `CHECKLIST.md` updated after each task.
