# Autonomous Procurement Assistant

An AI-assisted procurement platform for SMEs. It ingests messy supplier quotations —
digital PDFs, scanned pages, phone photos, spreadsheets — preserves the originals,
progressively extracts and normalizes them into one canonical structure, and ranks
suppliers using deterministic, auditable scoring.

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
cp .env.example .env    # then set JWT_SECRET_KEY (and GEMINI_API_KEY if you have one)
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
./.venv/Scripts/python.exe scripts/test_e2e.py           # 120 assertions against the live API
./.venv/Scripts/python.exe scripts/seed_demo.py          # populate a demo workspace
```

`test_e2e.py` requires the backend to be running.

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
| `AI_PROVIDER` | `gemini` | `gemini` or `none` |
| `GEMINI_API_KEY` | — | Without it the system degrades gracefully |
| `GEMINI_MODEL` | `gemini-2.0-flash` | |
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
| `GEMINI_API_KEY` | Optional | Heuristic extractor + computed (non-AI) explanation |
| Tesseract OCR | Optional | `rapidocr-onnxruntime` is the automatic pip-only fallback |

`OCR_ENGINE=auto` prefers Tesseract and falls back to RapidOCR, so installing
Tesseract later needs no code change.

---

## Not implemented

**Gmail and WhatsApp ingestion** are architecture only
(`app/integrations/ingestion/channels.py`). Both adapters are wired to the shared
ingestion service and report an explicit configuration error rather than failing
obscurely. Gmail needs an OAuth client and refresh token; WhatsApp needs the official
Meta Business Cloud API — an unofficial library is not an acceptable route for a
business product.

**Price anomaly detection** is deliberately simple: historical mean plus Z-score,
with an explicit `INSUFFICIENT_DATA` state so a single prior observation is never
presented as a statistical finding. Isolation Forest can be added behind the same
interface.
