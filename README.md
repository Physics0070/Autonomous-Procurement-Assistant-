# Autonomous Procurement Assistant

An AI-assisted procurement platform for SMEs. It ingests messy supplier quotations —
digital PDFs, scanned pages, phone photos, spreadsheets — preserves the originals,
progressively extracts and normalizes them into one canonical structure, and ranks
suppliers using deterministic, auditable scoring. On top of that it collects quotations
from Gmail, drafts RFQ and negotiation emails, raises purchase orders with the correct
GST split, orchestrates the work with LangGraph agents, answers questions through a
tool-using assistant, and predicts supplier late-delivery risk with a model trained on
real USAID shipment data.

**Core principle:** raw source → raw extraction → AI structured extraction →
canonical normalized data → comparison. Each layer is stored separately and later
layers never overwrite earlier ones.

---

## The pipeline

```
Uploaded / incoming document
        ↓  detect type (magic bytes → MIME → extension)
Text / table extraction        PyMuPDF · pandas/openpyxl · Pillow
        ↓  OCR only when a page has no usable text layer
Common raw representation      ProcessedDocument
        ↓
AI structured extraction       Gemini (heuristic parser when unconfigured)
        ↓  Pydantic validation — the model cannot invent fields
Validation                     inconsistencies flagged, never silently fixed
        ↓
Normalization                  deterministic → fuzzy → AI (only if ambiguous)
        ↓
Product matching               against the procurement request's items
        ↓
Supplier comparison            deterministic weighted scoring
        ↓
AI explanation                 describes the ranking; cannot change it
```

Manual upload, Gmail and WhatsApp all funnel through **one** ingestion service, so
document processing is never duplicated per channel.

---

## Running it

### Option A — Docker (everything, including Tesseract)

```bash
cp .env.example .env    # then set JWT_SECRET_KEY (and OPENROUTER_API_KEY / Google OAuth if you have them)
docker compose up --build
```

Frontend on <http://localhost:5173>, API on <http://localhost:8000>, docs at `/docs`.

### Option B — local

**1. MongoDB** must be listening on `127.0.0.1:27017`.

**2. Backend**

```bash
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
cp .env.example .env                                            # then set JWT_SECRET_KEY
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

**3. Frontend**

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to `127.0.0.1:8000`, so no CORS configuration is needed in dev.

---

## Verifying it works

Sample quotations are generated, not shipped — five documents in five formats from
four suppliers quoting the same requirement inconsistently.

```bash
cd backend
./.venv/Scripts/python.exe scripts/make_samples.py       # generate sample documents
./.venv/Scripts/python.exe scripts/test_extraction.py    # PDF/scan/image/Excel extraction
./.venv/Scripts/python.exe scripts/test_normalization.py # normalization + fuzzy matching
./.venv/Scripts/python.exe scripts/test_ai_extraction.py # structured extraction
./.venv/Scripts/python.exe scripts/test_e2e.py           # 147 assertions against the live API
./.venv/Scripts/python.exe scripts/seed_demo.py          # populate a demo workspace
./.venv/Scripts/python.exe -m scripts.load_scms_demo     # real-data demo org (USAID SCMS)
./.venv/Scripts/python.exe -m pytest -q                  # 144 unit/API tests (MongoDB needed)
```

`test_e2e.py` and `seed_demo.py` require the backend to be running. The pytest suite uses
a throwaway database (`procurement_assistant_test`), a fake Google backend and a scripted
fake LLM, so it needs no credentials.

The **SCMS demo organization** (`scms.demo@procurement-demo.com` / `ScmsDemo2026!`,
override with `SCMS_DEMO_EMAIL` / `SCMS_DEMO_PASSWORD`) holds 73 real suppliers and
10,324 delivered purchase orders in USD, so ML risk, anomalies, spend and forecasts can
be shown on real data. The reliability model was trained on the same shipments up to
2013, so in-app scores for this organization are partly in-sample; the held-out results
are in `backend/ml/artifacts/evaluation_report.md`.

---

## Architecture

```
API routes  →  services / business logic  →  repositories  →  MongoDB
```

MongoDB queries live **only** in `app/repositories/`. Business logic works with plain
dicts and Pydantic models, so the persistence engine could be replaced without
touching the procurement engine.

```
backend/app/
├── main.py                     FastAPI app, lifespan, error handlers
├── core/                       config · database · security · errors
├── api/
│   ├── deps.py                 auth + org-scoping dependencies
│   └── routes/                 auth · suppliers · procurement_requests
│                               documents · quotations · comparison · dashboard
├── schemas/                    API + domain models
│   ├── document.py             ProcessedDocument (the common raw representation)
│   ├── extraction.py           AI extraction contract + validation report
│   ├── normalized.py           canonical normalized data + match results
│   └── comparison.py           scores, rankings, explanation
├── repositories/               the only MongoDB-aware layer
├── services/
│   ├── documents/              detection · ocr · extractors/ · processor
│   │                           ingestion (one entry point) · ai_extraction · pipeline
│   ├── procurement/            validation · normalization · normalizer_service
│   │                           matching · comparison · explanation
│   │                           reliability · anomaly
│   └── storage/                StorageBackend abstraction + local implementation
├── integrations/
│   ├── ai/                     AIProvider → GeminiProvider · factory · prompts
│   └── ingestion/channels.py   Gmail / WhatsApp adapters (architecture only)
└── workers/processing.py       in-process async queue

frontend/src/
├── lib/api.ts                  single API client
├── features/auth.tsx           session context
├── hooks/queries.ts            all TanStack Query hooks
├── components/ui/              hand-written shadcn-style primitives
├── components/layout/          app shell + navigation
└── pages/                      Login · Dashboard · Requests · Documents
                                QuotationDetail · Suppliers · Comparison
```

### Collections

`users` · `organizations` · `suppliers` · `procurement_requests` · `quotations` ·
`comparisons` · `price_history`

Quotation items, processing history and corrections are **embedded**; suppliers and
requests are **referenced** because they are reused independently.

### Multi-tenancy

Every org-scoped repository forces queries through `_scope()`, which injects
`organization_id`. Cross-organization access is structurally prevented rather than
checked ad hoc.

---

## Design decisions worth knowing

**The model is never asked to do arithmetic.** Supplier scores and rankings are
computed in Python from configurable weights. Gemini receives the finished ranking
and writes prose about it. If it is unavailable, a clearly-labelled computed summary
is shown instead — never a fabricated one.

**Missing data stays missing.** The extraction prompt states the no-invention rule,
Pydantic enforces it, and the heuristic fallback leaves a field null when a line's
columns are ambiguous. In testing, an OCR-merged `100292` correctly produced *no*
quantity or unit price rather than a plausible guess.

**Corrections never overwrite machine output.** User edits are written to
`effective_data` with an entry in `user_corrections` recording the previous value.
`raw_content`, `ai_extraction` and `normalized_data` remain permanently auditable.

**OCR runs only where needed.** PDF pages are checked for a usable text layer first;
only pages below `PDF_TEXT_MIN_CHARS_PER_PAGE` get rendered and OCR'd.

**Reliability is rule-based, and says so.** There is not enough history for an ML
model, so the score is a transparent rule set with `method: "rule_based"` and
`is_ml_prediction: false` on every response.

---

## Environment variables

Backend (`backend/.env`, see `backend/.env.example`):

| Variable | Default | Notes |
|---|---|---|
| `MONGODB_URI` | `mongodb://127.0.0.1:27017` | |
| `MONGODB_DB_NAME` | `procurement_assistant` | |
| `JWT_SECRET_KEY` | — | **Required.** Generate your own |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` | 7 days |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Comma-separated |
| `STORAGE_BACKEND` | `local` | S3/MinIO slot in behind `StorageBackend` |
| `STORAGE_LOCAL_PATH` | `../storage` | Originals live here, not in MongoDB |
| `MAX_UPLOAD_SIZE_MB` | `25` | |
| `ENVIRONMENT` | `development` | Outside `development` the app refuses the placeholder `JWT_SECRET_KEY` |
| `AI_PROVIDER` | `openrouter` | `openrouter` · `ollama` · `gemini` · `none` |
| `OPENROUTER_API_KEY` | — | Free key at openrouter.ai. Without it: heuristic extraction, template drafts, assistant off |
| `OPENROUTER_MODEL` / `OPENROUTER_FALLBACK_MODELS` | `google/gemma-4-31b-it:free` / `nvidia/nemotron-3-super-120b-a12b:free` | |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `http://localhost:11434/v1` / — | Local, keyless alternative |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-2.0-flash` | Extraction only (no tool calling) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | — | Gmail OAuth client; without it the Integrations page says so |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/channels/gmail/callback` | Must match the Google Cloud client |
| `FRONTEND_URL` | `http://localhost:5173` | Where the OAuth callback returns |
| `TOKEN_ENCRYPTION_KEY` | derived from `JWT_SECRET_KEY` | Encrypts Gmail refresh tokens at rest |
| `GMAIL_SYNC_QUERY` / `GMAIL_MAX_MESSAGES_PER_SYNC` / `GMAIL_SYNC_INTERVAL_MINUTES` | quotation subjects, 30 days / `25` / `15` | `0` disables automatic sync |
| `NEGOTIATION_DEFAULT_DISCOUNT_PCT` | `5.0` | Target price below the quote |
| `NEGOTIATION_WEAK_CRITERION_SCORE` | `0.5` | Delivery/payment scores below this are negotiated |
| `ASSISTANT_MAX_TOOL_ROUNDS` | `6` | |
| `ML_MIN_RETRAIN_ORDERS` | `50` | Delivered POs needed to retrain on your own data |
| `OCR_ENGINE` | `auto` | `auto` · `tesseract` · `rapidocr` · `none` |
| `TESSERACT_CMD` | — | Only if `tesseract` is not on `PATH` |
| `PDF_TEXT_MIN_CHARS_PER_PAGE` | `60` | Below this, a page is treated as scanned |
| `PROCESSING_WORKER_CONCURRENCY` | `2` | |
| `SCORE_WEIGHT_*` | `0.40 / 0.20 / 0.15 / 0.15 / 0.10` | Price, delivery, payment, reliability, other |
| `MATCH_AUTO_THRESHOLD` | `0.86` | ≥ auto-match |
| `MATCH_REVIEW_THRESHOLD` | `0.62` | ≥ match but flag; below, manual review |

Frontend (`frontend/.env`): `VITE_API_BASE_URL` — leave empty in dev.

---

## External dependencies

| Dependency | Status | Effect if absent |
|---|---|---|
| MongoDB | Required | Backend will not start |
| `OPENROUTER_API_KEY` (or Ollama) | Optional | Heuristic extractor, computed explanation, template drafts; assistant returns 503 |
| Google OAuth client | Optional | Gmail collection unavailable (manual upload still works) |
| Tesseract OCR | Optional | `rapidocr-onnxruntime` is the automatic pip-only fallback |

`OCR_ENGINE=auto` prefers Tesseract and falls back to RapidOCR, so installing
Tesseract later needs no code change.

---

## Phases 3–6 at a glance

| Feature | Where | Notes |
|---|---|---|
| Gmail collection | Integrations page · `services/channels/gmail_sync.py` | `gmail.readonly` only; refresh token encrypted; dedup per message part; auto-sync every 15 min |
| RFQ and negotiation drafts | Communications page · `services/automation/communications.py` | LLM writes, template fallback; negotiation guardrail rejects any draft naming a competitor or its figures |
| Approval workflow | Communications page | draft → approved → sent; the app never sends email — export `.eml` or copy |
| Purchase orders | Purchase Orders page · `services/automation/purchase_orders.py` | Award from comparison; `PO-<year>-<0001>`; CGST+SGST / IGST / GST from GSTIN state codes; PDF; delivery recording |
| Agents (LangGraph) | `services/agents/` | Quotation processing graph, sourcing graph (stops at approval), assistant tool loop; every run recorded as a timeline |
| Procurement Assistant | Assistant page | 9 organization-bound tools; drafts only; max 6 tool rounds |
| ML late-delivery risk | Suppliers page · `backend/ml/` | Random forest on USAID SCMS; shown beside the rule-based score |
| Price anomalies | Quotation detail | Isolation Forest (+ out-of-range fence) from 20 past prices; Z-score below that |
| Spend and forecasts | Analytics page | Spend by supplier/month/item, on-time rate, savings; 3-month forecasts after 12 months of history |

### ML results (held-out test, 2014–2015, 2,545 shipments)

| Scorer | ROC-AUC | PR-AUC | Macro-F1 |
|---|---:|---:|---:|
| Random forest (selected by 5-fold CV PR-AUC) | 0.831 | 0.329 | 0.666 |
| Baseline: always on time | 0.500 | 0.140 | 0.462 |
| Baseline: supplier's prior on-time rate | 0.761 | 0.251 | 0.545 |

Accuracy is 77.4% against 86.0% for "always on time" — with 14% of shipments late,
accuracy rewards never predicting lateness, which is why PR-AUC and F1 are reported.
Full report: `backend/ml/artifacts/evaluation_report.md`; anomaly and forecast evaluation:
`backend/ml/artifacts/analytics_evaluation.md`.

---

## Not implemented

**WhatsApp ingestion** is architecture only (`app/integrations/ingestion/channels.py`):
it needs the official Meta Business Cloud API and a verified business account — an
unofficial library is not an acceptable route for a business product.

**Sending email and Google Drive** are out of scope by decision: drafts are approved in
the app and sent by a person; purchase orders download as PDF.
