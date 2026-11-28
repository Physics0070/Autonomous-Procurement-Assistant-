# Autonomous Procurement Assistant: Final Report

Group SY-K10, Department of Computer Engineering, Vishwakarma Institute of Technology, Pune. Academic year 2026-27, Semester I.
Team: Vishwajeet Surve, Soham Joshi, Soham Mote, Atharva Sonje. Guide: Prashant L. Mandale.
Report date: 20 November 2026. Every number in this report was measured on the project itself; sources are given beside each one.

## 1. Executive summary

The Autonomous Procurement Assistant is a web system for small and medium businesses in India. It reads supplier quotations from any source (PDF, phone photo, handwritten slip, Excel, Gmail), checks them, ranks the suppliers with transparent rules, and drafts the negotiation and the purchase order for a person to approve. Language models read text and write prose. Every number, ranking and tax split is computed in code, and nothing is sent or ordered without a person's approval.

| Area | Status |
|---|---|
| Features built against the synopsis | About 92%. Everything is built except WhatsApp collection. |
| Accuracy evidence | Strong on typed documents, weak on handwriting and on the forecast. |
| Automated tests | 8,420 pass, 60 skipped (about 8,200 are generated stress cases). |
| Ready for public use | About 6 of 10. Needs per-user limits, an AI spend cap and a hosted database. |
| Overall rating | 8 out of 10 for a student project. |

Headline numbers:

| Measure | Result | Data |
|---|---|---|
| Late-delivery risk, ROC-AUC | 0.832 [0.815 to 0.850]; the supplier's own record alone scores 0.761 | Real USAID SCMS, 2,545 later shipments |
| Extraction, fields correct | 96.6 to 96.9% (282 of 291 fields), 16 real quotations | Real documents, answers read by us |
| HSN code, heading accuracy | 91.2% [87 to 94] on general goods; 98.8% [93.6 to 99.8] on the easy benchmark | Benchmark and team-supplied set |
| Price errors, precision / recall | 0.75 / 1.00 | Team-supplied labelled file |
| Forecast error (3-month totals) | 21% to 55% depending on the series, always shown as a range | Real SCMS |
| Page endpoints | 8 to 21 ms median | Local, demo organization |

## 2. Problem and solution

Small businesses collect quotations as PDFs, photos, spreadsheets and e-mails, retype the figures, compare them by hand and write purchase orders with the GST split themselves. It is slow and error-prone. Enterprise procurement suites (SAP Ariba, Coupa, Zycus, GEP SMART) solve it but are costly and need ERP integration.

The system works in seven stages: collect, read, normalise, evaluate suppliers, recommend, automate drafts (RFQ, negotiation, purchase order), and analyse with machine learning. The pipeline keeps each layer separate and later layers never overwrite earlier ones: raw source, raw extraction, AI structured extraction, canonical normalised data, comparison.

Target users: purchase managers and procurement departments of small manufacturers, retailers and trading companies; warehouse and inventory managers.

## 3. Features

| Feature | Status | Notes |
|---|---|---|
| Login, organizations, per-company data separation | Works | Every database query is forced through an organization filter |
| Upload PDF, scan, photo, Excel (.xlsx, .xls), CSV | Works | Originals kept unchanged |
| Collect from Gmail (read-only) | Partly | Connected and syncing without errors; no real e-mail imported yet |
| WhatsApp collection | Not built | Needs Meta's WhatsApp Business Cloud API |
| OCR (Tesseract, RapidOCR fallback) | Works, slow on photos | 16 to 20 s per photo with RapidOCR; Tesseract not installed on the test machine |
| AI extraction with rule-based fallback | Works | |
| Validation: arithmetic, grounding, GST check digit | Works | Flags, never edits |
| Second reader (page image against text) | Works | Used for scans, photos and PDFs that carry page images |
| Original file beside the numbers, doubtful cells highlighted | Works | Quotation page |
| Normalisation of units, names, terms; item matching | Works | |
| Supplier comparison, scoring, ranking, explanation | Works | Scoring is code; the model writes the explanation |
| RFQ and negotiation drafts with a competitor guardrail | Works | Never sent automatically |
| Purchase orders: GST split, PDF, lifecycle, delivery recording | Works | CGST+SGST, IGST or plain GST from GSTIN state codes |
| Save purchase order to Google Drive | Works | Verified live |
| Multi-agent flow with approval pause and resume | Works | |
| Assistant with search over your own quotations and e-mails | Works | Keyword plus meaning search, 11 tools |
| Late-delivery risk model | Works, modest | Section 7.1 |
| Price-error detection | Works | Section 7.2 |
| Spend reports | Works | Cached, fast |
| Demand forecast | Works, rough | Shown with a range and a "how sure" label |
| HSN code suggestion | Works | Section 7.4 |
| Dark amber interface, plain-language wording | Works | Not every page checked on a phone |
| Public hosting | Not done | Docker and Render files ready |
| Per-user rate limits and AI spend cap | Not built | Needed before going public |

## 4. Architecture

```
Manual upload / Gmail  ->  one ingestion service (dedupe, store)
   ->  reading (text layer, OCR, page images)
   ->  AI extraction -> validation (arithmetic, grounding, GST) -> one self-correction
   ->  second reader on the page image -> reconcile or flag
   ->  normalisation (units, GST, HSN) -> MongoDB (organization-scoped)
   ->  supervisor agent + specialists | ML services | assistant
   ->  React dashboard (compare, negotiate, award, approve)  <->  FastAPI REST + JWT
```

Design rules that hold everywhere:
- The model never does arithmetic. Scores, rankings, GST splits and purchase-order totals are computed in Python.
- Every figure the model reports must appear in the document it read. Totals that are quantity x price are allowed.
- Missing data stays missing. Pydantic enforces the no-invention rule.
- Corrections never overwrite machine output. User edits go in `effective_data` with a record of the old value.
- Nothing is sent or ordered without approval. Agents produce drafts; a person approves.
- A supervisor may only choose a step the policy allows, and every agent run has a step budget.
- Multi-tenancy is structural: repositories inject the organization id into every query.

## 5. Technology stack

| Layer | Technology | Role |
|---|---|---|
| Frontend | React 19, TypeScript 6, Vite 8 | Single-page app |
| UI | Tailwind CSS 3, Radix UI, Lucide icons | Components, dark and light themes |
| Data fetching and charts | TanStack Query 5, Recharts 3 | Caching with retry on 502/503/504, reports |
| Backend | Python 3.12, FastAPI, Pydantic | REST API, validation |
| Database | MongoDB 7 with Motor (async driver) | 13 collections |
| Agents | LangGraph | Supervisor and specialist graph with pause and resume |
| LLM layer | One OpenAI-compatible provider class, automatic vendor fallback, council provider | Gemini, Groq, NVIDIA, optional OpenRouter, Ollama |
| OCR | Tesseract (preferred), RapidOCR (fallback), PyMuPDF for PDFs | Text from scans and photos |
| Spreadsheets | openpyxl, xlrd | .xlsx and old .xls |
| Machine learning | scikit-learn, pandas, NumPy, joblib | Risk model, price detector, forecast, search |
| Auth and security | JWT (HS256), password hashing, encrypted refresh tokens | |
| Integrations | Gmail API (read-only), Google Drive API, Google OAuth 2.0 | |
| Infrastructure | Docker, Docker Compose, Render blueprint | One image serves the API and the web app |
| Testing | pytest, generated stress cases, fault injection, real documents | Section 12 |

Code size: backend application 104 files and 12,474 lines; ML package 14 files and 2,118 lines; scripts 9 files and 1,367 lines; tests 42 files and 4,111 lines; frontend 34 files and 5,549 lines. About 25,600 lines in all; 43 commits.

## 6. AI models and routing

Each task has its own model chain written as `vendor:model|vendor:model`. If a vendor is rate-limited or fails, the next one is tried, and a failed vendor is put on a short cooldown. Vendors that cannot call tools are skipped in tool loops.

| Task | Chain (first is tried first) | Why |
|---|---|---|
| Extraction | Gemini 3.1 Flash-Lite, then Groq gpt-oss-20b, then NVIDIA Nemotron 3.5 Bolt | Gemini scored 98.2% of fields at 2.7 s in the benchmark |
| HSN codes | Gemini 3.1 Flash-Lite, then Groq Qwen 3.8 27B | 100% on 43 benchmark items |
| Page-image reading (second reader) | Gemini 3.1 Flash-Lite (the extraction chain; only Gemini accepts images) | 3.4 to 5.8 s per image |
| Embeddings | Gemini gemini-embedding-001 | Meaning-based search |
| Supervisor routing | Groq gpt-oss-20b, then NVIDIA Nemotron Bolt, then Groq Qwen | 0.6 s routing, 3 of 3 tool calls |
| Negotiation agent | Groq gpt-oss-20b, then NVIDIA Nemotron Bolt | No competitor leaked in 4 tempting e-mails |
| Assistant | NVIDIA Nemotron 3.5 Bolt, then Groq gpt-oss-20b | 3 of 3 tool calls at 1.3 s |
| Recommendation and critic | Council of three vendors | Cross-checks drafts |
| Council members | gpt-oss-20b or Nemotron Bolt; Nemotron Bolt or Qwen; Gemini Flash-Lite or Qwen | Different vendors so mistakes do not overlap |
| Council monitor | Groq Qwen 3.8 27B, then gpt-oss-20b, then Nemotron Bolt | Decides after anonymous peer review |

Seven models were benchmarked on four tasks (extraction, HSN, routing, e-mail leak test) plus tool calling. Gemini cannot call tools on its OpenAI-compatible endpoint, so it is marked text-only and agents skip it. Three models produced invalid runs because of timeouts or daily limits and are not counted.

Free-tier limits that matter: Groq allows 8,000 tokens a minute and 200,000 tokens a day per model, with 1,000 requests a day; Gemini sometimes returns 503 bursts; NVIDIA and OpenRouter free models have their own limits. The fallback chain absorbs this, but a public launch needs paid keys or per-user limits.

## 7. Machine learning and intelligence components

### 7.1 Supplier late-delivery risk (random forest)

| Item | Detail |
|---|---|
| Purpose | Probability that an order from a supplier arrives late |
| Algorithm | Random forest (300 trees, depth 8, minimum leaf 5, balanced subsamples), wrapped in sigmoid probability calibration |
| Chosen over | Logistic regression (CV ROC-AUC 0.775) and gradient boosting (0.876); forest 0.883 |
| Data | USAID SCMS delivery history, 10,324 real shipments, checksum-verified on every load |
| Split | By time. Train 2006 to 2013 (7,779 shipments, 10.67% late); test 2014 to 2015 (2,545 shipments, 13.99% late) |
| Features (10) | has_history, prior_count, prior_on_time_rate, prior_mean_delay_days, recent_late_rate, days_since_previous, log_order_value, log_quantity, shipment_mode, fulfil_via. Built only from shipments delivered 30 days before the scheduled date, so no outcome is leaked |
| Strongest signals | prior_count, prior_on_time_rate, recent_late_rate |
| Shipped threshold | 0.2906 (balanced F1); medium risk from 0.1453, high from 0.2906 |
| Retraining | On an organization's own delivered purchase orders once it has 50 or more |

| Test-period result | Value |
|---|---|
| ROC-AUC | 0.832 [0.815, 0.850] |
| PR-AUC | 0.334 [0.300, 0.380] |
| Baseline (supplier's prior on-time rate) | ROC-AUC 0.761 [0.740, 0.780]; gain +0.071 [0.054, 0.090], positive in every resample |
| By year | 2014: 0.843 (1,528 shipments); 2015: 0.800 (1,017) |
| Within groups | External vendors 0.808 (1,550 shipments, only 2.5% late); RDC shipments 0.562 (995 shipments, 32% late) |
| Shipped threshold | Flags 21.7% of orders; precision 0.358 [0.320, 0.397]; recall 0.553 [0.503, 0.604] |
| Screening threshold 0.1445 | Flags 40.8%; precision 0.317; recall 0.924 [0.896, 0.951] |
| Calibration | Brier 0.1671 before, 0.0985 after; expected calibration error 0.030 |

Reading: a clear, real gain over the simple record, well calibrated. The model ranks RDC shipments only a little better than chance, so much of the pooled score comes from separating the two shipment groups.
An order-feature study on the team's 4,000-order file (priority, promised lead time, shipping mode) reached ROC-AUC 0.71 on a later period against 0.66 for the supplier's late rate alone; a shuffled split gave the same 0.71, so that file has a ceiling near it.
Attempts to improve the model (a forest and boosting blend; selection on forward-in-time folds) scored worse on the test period (0.816 and 0.808) and were not kept.

### 7.2 Price-error detection

| Item | Detail |
|---|---|
| Purpose | Flag a quoted unit price that is far from what the same item usually costs |
| Method | z-score on log price against the item's own history; HIGH at 5 or more spreads, POSSIBLE at 2.7 or more; an Isolation Forest (200 trees) corroborates (z at least 2.7 and isolated gives HIGH) |
| History needed | 8 past prices |
| Chosen on | The first 150 labelled quotes by date; the later 150 were not used for any choice |
| Data | Team-supplied: 468 past purchases and 300 later quotes, 76 labelled wrong |

| Result | Value |
|---|---|
| Later 150 quotes, any flag | Precision 0.75 [0.63, 0.86]; recall 1.00 |
| Later 150 quotes, HIGH only | Precision 0.83 [0.71, 0.94]; recall 0.90 [0.79, 0.98] |
| Correct quotes wrongly flagged | 10.3% |
| Detection by size of error | Under 10% off the usual price: 0 of 2 caught; 10 to 20%: 2 of 4; 20% or more: all 70 |
| Recall by error type | Overcharge, decimal shift, unit mismatch, currency mix-up, suspiciously low: 100%; GST added twice: 80%; digit transposition: 75% |
| Before the rebuild (old percentile cut-offs) | Precision 0.47, recall 0.96, 36% of correct quotes flagged |
| On real SCMS prices | 1.6% flagged (11.1% before); SCMS has no error labels |

### 7.3 Demand forecast

| Item | Detail |
|---|---|
| Method | Croston's method with the Syntetos-Boylan correction (built for lumpy orders); the mean of the last 12 months, linear trend and last year's value compete, and another method must cut the backtest error by 25% to replace Croston |
| Output | Monthly quantity for the next months, a likely range (10th to 90th percentile of past forecast misses), error percentage, and a label (fair, rough, poor) |
| Rules | Needs 12 months of history; a short history never earns "fair"; the current unfinished month is left out |
| Error measure | Total miss divided by total demand over 3-month periods, at 12 cut-off months |

| Series (real SCMS) | Croston (used) | Linear trend |
|---|---|---|
| ARV quantity | 30% | 38% |
| HRDT quantity | 55% | 58% |
| All shipments, order value | 31% | 35% |
| All shipments, count | 21% | 26% |

The range covered 75 to 78% of the actual months (aimed at 80%). The label is only a crude guide. SCMS records 27, 1, 0 and 2 shipments in its last four months because later shipments were not yet logged; earlier forecast tests that scored against those months were wrong and are withdrawn.

### 7.4 HSN code suggestion (text matching plus language model)

Stage 1 ranks all 1,000+ official headings by TF-IDF similarity (character and word n-grams, trade shorthand such as MS, GI, TMT expanded) against the GST portal's HSN master of 21,935 codes. Stage 2 asks a language model to choose among the top 30; its answer must exist in the master, so it cannot invent a code. With no model, the closest of the 750 team-labelled items is used.

| Test | Result |
|---|---|
| Original benchmark, 85 held-out items | Text matching 54.1%; with model **98.8%** [93.6, 99.8]; chapter 100% |
| Broader labelled set, 250 items | With model **91.2%** [87.0, 94.1] (first 100: 94.0%; next 150: 89.3%) |
| Broader set, 750 items | Text matching alone 27.6%; right answer inside the shortlist 79.6% |
| No model | Closest labelled item 53% |
| Showing similar labelled items to the model | Tried: 92.0% against 94.0%, so not used |

Latency: median 1.4 s, slow tail about 9 s from Gemini retries.

### 7.5 Extraction pipeline

| Part | Detail |
|---|---|
| Reading | Text layer first; only pages without text are rendered and OCR'd |
| Extraction | Model returns a strict JSON schema; Pydantic is the gate; a rule-based reader is the fallback |
| Validation | Arithmetic (line totals, subtotal, total with tax and freight), implausible values, missing fields, GST format and check digit |
| Grounding check | Every price, quantity, total and identifier must appear in the source text; computed totals allowed; an OCR-glued number counts as read |
| Self-correction | One re-read when errors are found, using the validator's complaints |
| Second reader | The page image is read separately; disagreements on an amount are flagged; an amount with one extra trailing digit ("/-" read as a digit) is corrected from the image; if the text reading found no items, the image reading is used and marked |
| Incomplete lines | Any line missing a quantity or price needs review |
| PDFs with page images | Also read as images, because an image can show different figures from the text layer |

Accuracy on 16 real quotations (typed PDFs, phone photos, handwritten slips), 291 fields (quantity, rate, line total, grand total), correct answers read from the documents by us:

| Kind | Documents | Fields right |
|---|---|---|
| Typed phone photos | 4 | 98.0% |
| Digital PDFs | 10 | 97.8% |
| Handwritten slips | 2 | 56 to 67% |
| All | 16 | 96.6 to 96.9% over three runs (the text reading alone: 94.8 to 95.5%) |

Four of 16 documents were flagged for review. Known failures: handwriting; one quotation with swapped Our Rate and Qty headings and a first row without units; one quotation whose page picture differs from its text layer (now flagged).

### 7.6 Supplier scoring (rules, not machine learning)

Five scores between 0 and 1, combined with default weights: price 0.40, delivery 0.20, payment terms 0.15, supplier reliability 0.15, other terms 0.10. For price and delivery the smallest value scores 1 and the largest 0; payment terms use the mirror rule. Missing data receives a fixed low score and a visible note. Weights can be changed and are normalised. The supplier reliability score is a performance scorecard from the organisation's own orders: on-time in-full delivery 30%, quality (quantity rejected at inspection) 30%, fulfilment (orders the supplier cancelled) 15%, commercial (invoice within the order total) 15%, responsiveness (days to reply to a quote request) 10%. A factor with no records is left out and its weight shared, and a supplier with fewer than 3 completed orders is shown as a new supplier with a neutral 0.5 in the ranking. The ML late-delivery risk is shown beside it.

### 7.7 Other components

| Component | Detail |
|---|---|
| GSTIN check digit | The GST network's base-36 checksum. The published sample and 4 of 4 GSTINs from real quotations pass; changing any one character fails (300 generated cases) |
| Search over your records | TF-IDF keyword search plus Gemini embeddings (cosine at least 0.62 counts as related), cached in memory, keyword fallback if embeddings fail; every hit names its record |
| Past-price lookup | Similar items found by character n-grams and embeddings. The assistant sees suppliers and dates; the negotiation agent sees only anonymous price ranges and this supplier's own earlier prices, so no competitor can leak |
| LLM council | Members answer, review each other anonymously, and a monitor decides; failing members are dropped |
| Negotiation guardrail | Deterministic check that rejects any draft naming a competitor or quoting its figures; the critic agent is a second layer |

## 8. Datasets

| Dataset | Size | Source | Use |
|---|---|---|---|
| USAID SCMS delivery history | 10,324 shipments | USAID, data.usaid.gov dataset a3rc-nmf6; SHA-256 verified on load | Risk model, price-anomaly check, forecasts |
| GST HSN master | 21,935 codes | GST portal | HSN suggestion |
| HSN benchmark | 114 items (29 development, 85 held out) | Hand-labelled, checked against the master | HSN tuning and test |
| HSN labelled set | 750 items | Supplied by the team | Broad HSN test, no-model fallback |
| Order file | 4,000 orders, 14 suppliers | Supplied by the team | Order-feature study |
| Price history and labelled quotes | 468 purchases; 300 quotes (76 wrong) | Supplied by the team | Price-error detector |
| Real quotations | 16 documents scored (23 distinct files tried) | The team's own collection (private, not in the repository) | Extraction accuracy |

The team describes its supplied files as real vendor data. Their source has not been independently verified, and they are labelled that way in the repository.

## 9. Agents and assistant

| Agent | Decides | Tools of its own |
|---|---|---|
| Supervisor | Which specialist runs next, and when to stop for approval | Picks from actions the policy allows |
| Document extraction | Whether its own reading is good enough | Re-reads once with validator complaints |
| Matching | Which quoted line answers which requested item | AI adjudication for ambiguous pairs only |
| Comparison | Nothing; scoring stays deterministic | None |
| Recommendation | How to explain the ranking | None |
| Risk | Whether the supplier's record is a concern | The ML risk model |
| Negotiation | What to argue and how | Supplier performance, price history, similar past prices, past negotiations, guardrail-checked submit |
| Critic | Whether a draft is fit to send | None |
| Purchase order | Nothing; tax and totals stay deterministic | None |
| Monitor | When work should start unasked | Starts sourcing on new quotations; chases overdue deliveries |
| Assistant | How to answer a question | 11 tools, below |

Assistant tools (all bound to the caller's organization on the server): list_procurement_requests, get_procurement_request, search_quotations, get_quotation, get_comparison, get_supplier, spend_summary, search_records, similar_past_prices, draft_rfq, draft_negotiation. At most 6 tool rounds per answer; drafts only.

## 10. API reference

Base path `/api/v1`, JSON, bearer-token (JWT) authentication except register and login. Interactive documentation is served at `/docs`. 60 endpoints in 14 groups.

| Group | Endpoints |
|---|---|
| System (2) | GET /health; GET / |
| Auth (3) | POST /auth/register; POST /auth/login; GET /auth/me |
| Organizations (2) | GET /organizations/me; PUT /organizations/me |
| Suppliers (4) | GET, POST /suppliers; GET, PUT /suppliers/{id} |
| Purchase requests (5) | GET, POST /procurement-requests; GET, PUT, DELETE /procurement-requests/{id} |
| Documents (2) | POST /documents/upload; GET /documents/capabilities |
| Quotations (6) | GET /quotations; GET /quotations/{id}; GET /quotations/{id}/file; POST /quotations/{id}/reprocess; PATCH /quotations/{id}/link; POST /quotations/{id}/corrections |
| Comparison (3) | GET /comparisons/weights; POST, GET /comparisons/procurement-requests/{id} |
| Dashboard (1) | GET /dashboard/summary |
| Channels (4) | GET /channels; GET /channels/gmail/authorize; POST /channels/gmail/sync; DELETE /channels/gmail |
| Communications and orders (15) | GET /communications; GET, PATCH /communications/{id}; POST /procurement-requests/{id}/rfqs; POST /comparisons/procurement-requests/{id}/negotiations; POST /communications/{id}/approve, /mark-sent, /cancel; GET /communications/{id}/eml; POST /comparisons/procurement-requests/{id}/award; GET /purchase-orders; GET /purchase-orders/{id}; POST /purchase-orders/{id}/drive; POST /purchase-orders/{id}/{action}; GET /purchase-orders/{id}/pdf |
| Agents (5) | POST /agents/sourcing/{request_id}; POST /agents/supervisor/{request_id}; POST /agents/runs/{run_id}/resume; GET /agents/runs; GET /agents/runs/{run_id} |
| Assistant (3) | POST /assistant/messages; GET /assistant/conversations; GET /assistant/conversations/{id} |
| Analytics (5) | GET /analytics/spend; GET /analytics/forecast; GET /analytics/hsn; GET /analytics/models; POST /analytics/models/reliability/retrain |

Errors use one envelope with a message. Gateway failures (502, 503, 504) on reads are retried automatically by the web app and shown in plain words.

## 11. Data model and integrations

Collections: users, organizations, suppliers, procurement_requests, quotations, comparisons, price_history, channel_connections, communications, purchase_orders, counters, agent_runs, conversations. Quotation items, processing history and corrections are embedded; suppliers and requests are referenced. Purchase-order numbers come from an atomic per-organization counter (PO-year-0001).

| Integration | Status |
|---|---|
| Gmail (read-only) | Connected; sync runs every 15 minutes; refresh token encrypted; no real e-mail imported yet |
| Google Drive | Upload of purchase-order PDFs verified live |
| Google OAuth 2.0 | Client configured; app is in Google's Testing mode, so the connection expires after 7 days |
| WhatsApp Business | Not built |

Settings are read from the environment. Main names: MONGODB_URI, MONGODB_DB_NAME, JWT_SECRET_KEY, TOKEN_ENCRYPTION_KEY, ENVIRONMENT, GEMINI_API_KEY, GROQ_API_KEY, NVIDIA_API_KEY, OPENROUTER_API_KEY, LLM_TASK_MODELS, COUNCIL_MODELS, COUNCIL_MONITOR_MODEL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, GOOGLE_DRIVE_ENABLED, GOOGLE_DRIVE_FOLDER_ID, FRONTEND_URL, OCR_ENGINE, VISION_SECOND_READER, EXTRACTION_SELF_CORRECTION, SCORE_WEIGHT_*, ML_MIN_RETRAIN_ORDERS, ASSISTANT_MAX_TOOL_ROUNDS, AGENT_AUTOPILOT, STORAGE_BACKEND, CORS_ORIGINS. A placeholder JWT secret is refused outside development.

## 12. Testing and validation

| Test group | Count | What it proves |
|---|---|---|
| Hand-written unit, API and graph tests | about 280 | Behaviour of each feature, agent graph, Google and Drive with fakes |
| Validation and grounding stress cases | about 2,300 | Clean quotations raise nothing; inflated prices, changed totals, invented prices, invented GST numbers and dropped lines are caught |
| Second-reader stress cases | 1,200 | An extra trailing digit is always corrected; a real difference is never changed |
| Price-detector stress cases | 700 | Ordinary prices pass; far outliers are always flagged; deterministic |
| GST and GSTIN stress cases | 1,200 | Tax split adds up; every one-character GSTIN error fails |
| Parsing stress cases | 1,400 | Garbage never raises; Indian-format amounts are read exactly |
| Ranking, search, forecast stress cases | 1,400 | Cheapest ranks first; scaling prices keeps the order; forecasts never negative, sane ranges |
| **Total** | **8,420 passed, 60 skipped** | Skips are single-line quotations or lines under the 2% tolerance |

Validation methods: time-ordered splits, bootstrap confidence intervals (2,000 resamples), paired gain over a baseline, calibration error, per-year and per-group results, twelve cut-off months for forecasts, difficult real documents, and fault injection. The full write-up is `docs/VALIDATION_REPORT.md`.

Faults found by this testing and fixed: forecast crashed on short series (twice); photos took 53 s to read (OCR threads, now 16 s); a quotation with a missing quantity or price passed as fine; a PDF whose picture differed from its text layer was trusted; a misread GST number looked valid; the HSN figure was optimistic (revised to 91% for general goods); forecasts had been scored against months SCMS never recorded.

## 13. Performance

Measured from the client over 127.0.0.1 on a 16-thread laptop with a local database and free-tier AI keys. The demo organization holds 9 quotations.

| Operation | Median | 95th percentile |
|---|---|---|
| Login (password hashing) | 0.45 s | 0.46 s |
| Dashboard, quotations, detail, suppliers, requests, orders, e-mails, comparison | 8 to 21 ms | under 30 ms |
| Reports: spend, forecast, models | 7 to 12 ms | under 15 ms |
| 20 users on the dashboard at once | 0.23 s | 0.27 s; 77 requests a second; 0 errors in 100 |
| HSN suggestion (model) | 1.4 s | 9.0 s |
| Assistant answer (model and tools) | 1.7 s | 3.9 s |
| Embedding call (3 texts) | 0.56 s | 0.62 s |
| Short model call | 0.37 s | 0.67 s |
| Reading a typed PDF, start to finish | 6.6 s | 14.4 s |
| Reading a typed phone photo | 29.7 s (was 53 s) | 38.7 s |
| Reading a handwritten photo | 17.5 s (was 31 s) | 19.7 s |

A first load of Reports on the 10,324-order SCMS organization took about 2 s when last measured, then about 0.1 s from cache. Photo reading is dominated by OCR (about 20 s with RapidOCR); installing Tesseract would shorten it.

## 14. Security and safety

- Passwords hashed; JWT access tokens; the placeholder secret is refused outside development.
- Gmail refresh tokens stored encrypted; read-only Gmail scope; Drive limited to files the app creates.
- Organization scoping is forced inside every repository, so cross-company access is structurally prevented and tested.
- No API key has ever been committed (tracked files and full history scanned); keys live in an untracked environment file.
- Agents cannot send or order; drafts need approval; a deterministic guardrail blocks competitor leaks; run step budgets prevent runaway loops.
- Invented or misread figures are caught by the grounding check, arithmetic checks, the GST check digit and the second reader.
- Not built yet: per-user rate limits and an AI spend cap. Anyone with the public address could use up the shared free-tier keys, so these come before any public launch.

## 15. Deployment and operations

| Item | Detail |
|---|---|
| Local | Backend (uvicorn, port 8000), frontend (Vite, port 5173), MongoDB on 27017 |
| Docker | Compose file with MongoDB, backend (with Tesseract) and frontend |
| One-site image | Root Dockerfile builds the web app and serves it with the API from one address |
| Render | `render.yaml` blueprint for a single web service; needs a hosted database (MongoDB Atlas) and the keys entered as environment variables |
| Google | The redirect address must match the live address; Testing mode needs a weekly reconnect until Google reviews the app |
| Costs | Everything runs on free tiers today; paid usage has not been estimated here (see the project report's cost section) |

## 16. Limitations and risks

| Limitation | Effect |
|---|---|
| Handwriting reading is weak (2 documents, 56 to 67%) | Handwritten slips always need a person to check them |
| Forecast is rough (21 to 55% error) | Shown as a range, not a promise |
| Risk model weak inside RDC shipments (0.562) | Value comes from supplier history, mostly for external vendors |
| Price-error results are on a team-supplied file with injected-style labels | Not proof of field accuracy; errors under 10% are missed |
| Extraction sample is 16 documents, mostly typed | Real accuracy on other layouts is unproven |
| Free-tier AI limits | Fallback helps, but a public launch needs paid keys or limits |
| A missing line under 3% of a subtotal is within the 2% tolerance | Goes unflagged |
| Gmail never imported a real e-mail | Built, connected, but not proven end to end |
| Photos take about 30 s to read | Mostly OCR on CPU |

## 17. Upgrade plan

| Priority | Upgrade | Why |
|---|---|---|
| 1 | Install Tesseract; clean images before OCR | Photo reading is the slowest step |
| 2 | Per-user rate limits and an AI spend cap; deploy on Atlas and Render | Required for a public launch |
| 3 | Collect 20 or more real quotations with correct values, including handwriting | Turns small samples into real accuracy figures |
| 4 | Import a real e-mail through Gmail | The only built feature never tried end to end |
| 5 | Make the page-image reading the main one for low-confidence scans | Fixes handwriting; the vision model already read both slips correctly |
| 6 | Cross-supplier price check for swapped quantity and rate columns | One known wrong-way-round case |
| 7 | Real vendor delivery history of 1,500 or more orders | Improves the risk model beyond supplier history |
| 8 | Check every page on a phone and in every state | Not fully checked |
| 9 | Move Google out of Testing mode | Removes the weekly reconnect |
| 10 | WhatsApp collection | Listed in the synopsis as future work |

## 18. Overall rating

| Area | Rating |
|---|---|
| Features against the synopsis | 9 / 10 |
| Accuracy evidence | 7.5 / 10 |
| Speed | 8 / 10 (photos are the slow spot) |
| Safety (no invented numbers, approval before sending) | 9 / 10 |
| Ready for public use | 6 / 10 |
| Documentation | 9 / 10 |
| **Overall** | **8 / 10** |

## 19. How to reproduce

From `backend/` with MongoDB running:

```
pytest -q                                  # all tests, about 6 minutes
python -m ml.validate_numbers              # risk, price-error and forecast numbers with intervals
python -m ml.train_reliability             # retrain the risk model on SCMS
python -m ml.evaluate_analytics            # price-anomaly and forecast report on SCMS
python -m ml.price_errors_eval             # price-error report on the labelled file
python -m ml.sme_orders_eval               # order-feature study
python -m ml.hsn dev test --llm            # HSN accuracy with the model
python scripts/measure_latency.py --ai     # API latency (needs DEMO_EMAIL and DEMO_PASSWORD)
```

Reports are written to `backend/ml/artifacts/`. Further documents: `README.md` (overview and setup), `docs/TECHNICAL_REFERENCE.md` (design detail), `docs/VALIDATION_REPORT.md` (every number with intervals), `CHECKLIST.md` (build log).
