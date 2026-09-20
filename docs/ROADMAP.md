# Roadmap — aligned to the project synopsis

Source of truth: `Synopsis.pdf` (FF No 180, Group SY-K10, *Autonomous Procurement
Assistant using Multi-Agent AI and Machine Learning*). Phases 1 and 2 were built
from earlier briefs; this document re-maps all work onto the synopsis's key
features, methodology stages and architecture modules.

Status as of 18 Sep 2026 — Phases 1–6 built; live AI and Gmail await the team's keys.

---

## 1. Where the build stands against the synopsis

### Key features (17 bullets)

| # | Synopsis item | Status | Evidence / gap | Phase |
|---|---|---|---|---|
| 1.1 | Automatic quotation collection from Gmail | **Done** | OAuth, sync, dedup, scheduler; tested against a fake Google (needs team's OAuth client for live) | 3 |
| 1.2 | Upload PDF, Excel, images, scanned | **Done** | `test_extraction.py` 5/5 formats | 2 |
| 1.3 | WhatsApp Business integration *(future)* | Architecture only | Stub in `integrations/ingestion/channels.py` | Future |
| 2.1 | OCR extraction from scanned documents | **Done** | RapidOCR in use; Tesseract engine built but needs admin install | 2 |
| 2.2 | Automatic supplier information extraction | **Done** | Heuristic parser verified; Gemini path built, live call unverified | 2 |
| 2.3 | Products, quantities, unit prices, GST, delivery, payment terms | **Done** | Delivery captured as lead-time days **and** a stated delivery date | 2 |
| 3.1 | Standardise quotation formats | **Done** | `normalizer_service.py`; Hindi item matches English at 1.00 | 2 |
| 3.2 | Compare on multiple parameters | **Done** | Transport cost has its own column | 4 |
| 3.3 | Supplier ranking with explanation | **Done** | Deterministic ranking; explanation is computed until an LLM is available | 2 |
| 4.1 | Generate RFQ emails | **Done** | LLM + template fallback; approval workflow; `.eml` export | 4 |
| 4.2 | Draft negotiation emails | **Done** | Competitor guardrail; target price; weakest criteria | 4 |
| 4.3 | Generate purchase orders | **Done** | Award, GST split, lifecycle, PDF, delivery recording | 4 |
| 4.4 | Conversational procurement recommendations | **Done** | LangGraph assistant, 9 org-bound tools (live answers need `OPENROUTER_API_KEY`) | 5 |
| 5.1 | Supplier reliability **prediction** | **Done** | Calibrated random forest on USAID SCMS; ROC-AUC 0.83, PR-AUC 0.33 vs 0.25 baseline, Brier 0.099 vs 0.111 | 6 |
| 5.2 | Price anomaly detection | **Done** | Isolation Forest from 20 prices; Z-score below | 6 |
| 5.3 | Procurement spending analytics | **Done** | Analytics page: spend, on-time, savings | 6 |
| 5.4 | Demand forecasting *(future)* | **Done** | Linear trend vs seasonal naive, back-tested | 6 |

**Count, excluding the two items the synopsis marks as future:** 15 of 15 done
(WhatsApp remains future work, as the synopsis marks it).

### Technology stack

| Synopsis | Status |
|---|---|
| React.js, Tailwind CSS, JavaScript | Done — written in TypeScript, which compiles to JavaScript |
| Python, FastAPI | Done |
| PostgreSQL / MongoDB | MongoDB done; repository layer keeps PostgreSQL swappable |
| Ollama / Gemini API | OpenRouter (primary), Ollama and Gemini providers built; key needed for live calls |
| **LangGraph** | Done — supervisor + 5 specialists with handoffs, processing graph, assistant loop |
| OCR (Tesseract / LlamaParse) | Tesseract engine built, not installable on this machine; RapidOCR used |
| **Scikit-Learn** | Done — random forest, Isolation Forest, linear regression |
| Pandas | Done |
| **Gmail API, Google OAuth 2.0** | Done (read-only) |
| Google Drive API | Done — purchase orders file to Drive (`drive.file` scope, same Google connection) |

### Architecture modules (synopsis diagram)

| Module | Status | Phase |
|---|---|---|
| Data Collection | Done — upload + Gmail | 3 |
| OCR & AI Document Extraction | Done | 2 |
| Data Normalization | Done | 2 |
| AI Procurement Engine (LLM + Agentic AI) | Done — supervisor-routed multi-agent system with pause/resume | 5 |
| Machine Learning Module | Done | 6 |
| Supplier Comparison Engine | Done | 2 |
| AI Recommendation Module | Done | 2 |
| Email Generation & Purchase Order Generation | Done | 4 |
| User Approval | Done — drafts and POs need approval | 4 |
| Execution (send emails / save PO) | Done — `.eml` export, mark sent, PO PDF (no automatic sending, by decision) | 4 |
| Procurement Dashboard | Done — plus Analytics page | 6 |

### Methodology stages

| Stage | Status |
|---|---|
| 1. Data Collection | Done |
| 2. Document Processing | Done |
| 3. Data Normalization | Done |
| 4. Supplier Evaluation | Done |
| 5. AI Recommendation | Done |
| 6. Procurement Automation | Done |
| 7. Machine Learning Analysis | Done |

---

## 2. Phases

### Phase 1 — Foundation · **Done**
Accounts, organizations with enforced isolation, procurement requests, suppliers,
file storage outside the database, document upload.

### Phase 2 — Document intelligence and supplier comparison · **Done**
Methodology stages 2–5. Extraction, OCR, validation, normalization, product
matching, deterministic scoring, explanation, review and comparison screens.
120 end-to-end assertions passing.
*Open item:* the live Gemini call is unverified until a key is supplied.

### Phase 3 — Gmail ingestion · **Done**
Methodology stage 1; synopsis APIs *Gmail API* and *Google OAuth 2.0*.

- Connect a Gmail mailbox with Google OAuth 2.0 (read-only scope).
- Automatic and on-demand collection of quotation attachments and quotation text in
  email bodies, through the same ingestion pipeline as manual upload.
- No duplicates on repeat syncs; sender linked to a known supplier.
- Refresh tokens encrypted at rest; revoked access surfaces as "reconnect".
- Integrations screen.

WhatsApp stays architecture-only — the synopsis scopes it as future support, and
Meta's WhatsApp Business Cloud API needs a verified business account and a public
HTTPS webhook, which a local demo cannot provide.

Detailed task plan: `docs/superpowers/plans/2026-09-17-gmail-ingestion.md`

**Exit criteria:** pytest suite passes against simulated Google responses; a real
mailbox connected and a real emailed quotation imported and processed.
**Needs from the team:** a Google Cloud OAuth client (free) — steps in the plan, Task 9.

### Phase 4 — Procurement automation · **Done**
Methodology stage 6; modules *Email Generation & PO Generation*, *User Approval*,
*Execution*; key features 4.1–4.3.

- **RFQ drafts** generated from a procurement request, one per chosen supplier.
- **Negotiation drafts** grounded in the comparison: target price, delivery or
  payment asks. Drafts must never disclose another supplier's name or quote.
- **Purchase orders:** award a supplier from the comparison, generate a PO with a
  per-organization PO number and GST breakup, render it to PDF.
- **Approval workflow:** every draft moves `draft → approved → sent`; nothing leaves
  the system without a named user's approval, as the synopsis requires.
- **Execution:** send approved emails through the connected Gmail account
  (adds the `gmail.send` scope via incremental consent); optionally save PO PDFs to
  Google Drive.
- Surface transportation cost as its own comparison column (closes 3.2).
- Template-based drafts when no LLM is configured, clearly labelled.

**Exit criteria:** request → RFQs approved and sent → quotations arrive via Gmail →
comparison → award → PO approved → PO emailed, all demonstrable end to end.

### Phase 5 — Multi-agent orchestration · **Done**
The title's *Multi-Agent AI*; module *AI Procurement Engine (LLM + Agentic AI)*;
key feature 4.4.

- **Ollama provider** alongside Gemini, so the agents run on a free local model.
- **LangGraph** state graph over the existing services, with named agents matching
  the synopsis references: Document Extraction Agent, Comparison Agent,
  Negotiation Agent, Procurement Assistant.
- LangGraph interrupts implement the *User Approval Module* as human-in-the-loop
  checkpoints.
- **Conversational assistant** with tools over the organization's own data
  (search quotations, explain a comparison, draft an RFQ), with a chat screen.
- Agents orchestrate existing services; scoring stays deterministic.

**Exit criteria:** a graph run is visible step by step in the UI; the assistant
answers questions with citations to real quotations and refuses to invent figures.
**Blocked on:** an LLM — a free Gemini key from Google AI Studio, or Ollama.

### Phase 6 — Machine learning analytics · **Done**
Methodology stage 7; module *Machine Learning Module*; key features 5.1–5.4.

- **Reliability prediction** with scikit-learn (gradient boosting or logistic
  regression) on delivery and quality history. Training data: a documented,
  seeded synthetic history plus the organization's own records once enough exist.
  Report held-out metrics; show model version and data provenance in the UI; keep
  the rule-based score as the fallback when data is insufficient.
- **Price anomaly detection** with Isolation Forest, replacing the Z-score where the
  history is large enough.
- **Spend analytics:** spend by supplier, category and month; savings versus
  average quoted price; reports.
- **Demand forecasting** (stretch): per-item forecasts from purchase-order history.

**Existing starting point:** `supplier_model_training.ipynb` (reviewed 17 Sep 2026).
Its workflow is reusable — per-vendor aggregation, score bounds fitted on the
training split only, a Decision Tree / Random Forest / XGBoost comparison, and a
prediction function returning class, confidence and reasons. It is **not yet a
reliability predictor**, and these must be fixed before it is integrated or
presented:

- **Circular target.** The class being predicted is computed by a business-rule
  formula from the same features the models receive, so the models learn to
  imitate that formula. The formula itself is exact; the model can only be worse.
  Use a label the features don't determine — ideally a later-period outcome
  (e.g. lead time from PO to receipt, if the purchase data has those dates).
- **Features the app doesn't have.** Profit margin, stock turnover and
  sales-to-purchase ratio describe how well the buyer *resells* a vendor's goods,
  and require sales data. A quotation provides price, quantity, freight, delivery
  and payment terms. Only 4 of the 8 features map onto what the pipeline extracts.
- **Too little test data to rank models.** 132 vendors → 27 test rows; XGBoost
  (25/27) beats Random Forest (23/27) by two rows. Use stratified k-fold
  cross-validation.
- **No baseline reported.** 78% of vendors are "Average"; always answering
  "Average" scores 21/27 — exactly the Decision Tree's result. Report this
  baseline and macro-F1.
- **Contradictory explanations.** The sample prediction classes a supplier as
  *Poor* while listing only positive reasons ("High profit margin", "High stock
  turnover").
- **Imputation hides "no sales".** Vendors with zero sales receive the median
  +22.4% margin. Add a no-sales indicator instead.
- **Not runnable here.** Hardcoded paths (`OneDrive\...\ChatGPT\EDI`,
  `C:\EDI\datasets`) don't exist on this machine; the notebook ran on Python 3.14
  while the backend is 3.12, and pickled scikit-learn models are version-bound.
  Move the code and data into the repository and retrain in the backend
  environment.

**Exit criteria:** models trained, evaluated and versioned; every prediction labels
its method; analytics screens run on real aggregates.
**Note:** this phase does not need an LLM — if LLM access is still missing after
Phase 3, do Phase 6 before Phases 4 and 5.

### Phase 7 — Review readiness
- Pytest suite covering every phase; one-command test run.
- Progress Review 1 (mid-semester) and Review 2 (end of semester) reports.
- Demo dataset and scripted walkthrough; architecture diagram matched to the build.
- WhatsApp Business design note as documented future work.
- Deployment via Docker Compose (includes Tesseract).

---

## 3. Recommended order

```
Phase 3 Gmail ──► obtain LLM access ──► Phase 4 Automation ──► Phase 5 Agents ──► Phase 6 ML ──► Phase 7
                          │
                          └── no LLM yet? ──► Phase 6 ML first, then 4 and 5
```

Why this order: Gmail completes the synopsis's primary data source and is also the
send channel Phase 4 needs. Phases 4 and 5 are language-model work. Phase 6 is
independent and can move forward if LLM access is delayed.

---

## 4. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Title promises multi-agent AI and ML; neither exists yet | Most likely review question | Prioritise Phases 5 and 6 before Review 2; be explicit at Review 1 about what is built |
| No LLM access | Blocks drafting, agents, chat and the AI explanation | Free Gemini key from Google AI Studio, or Ollama |
| Too little real history for ML | A model on thin data is not meaningful | Documented synthetic data, held-out metrics, rule-based fallback, honest labels |
| Google OAuth app in *Testing* mode | Only listed test users can connect; tokens expire after 7 days | Add all four team members as test users; reconnect before demos |
| Tesseract needs admin rights here | RapidOCR used locally instead | Docker image installs Tesseract |

---

## 5. Corrections for the synopsis document

- **Soham Joshi:** P.R. No. is `1251070775`, but the email is
  `soham.1251070812@vit.edu`. One of the two is wrong.
- **Product name:** the title says *Autonomous Procurement Assistant*; the synopsis
  body calls it *AI Procurement Copilot*. Pick one.
- **Stack:** the frontend is TypeScript (a typed superset of JavaScript); the
  database chosen is MongoDB.
