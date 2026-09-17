# Phases 3–6 design — Gmail, procurement automation, agents, machine learning

Date: 17 Sep 2026 · Source requirements: `Synopsis.pdf`, `docs/ROADMAP.md`

## Decisions already made

| Topic | Decision |
|---|---|
| LLM provider | **OpenRouter, free models.** Primary `google/gemma-4-31b-it:free`, fallback `nvidia/nemotron-3-super-120b-a12b:free` (both support tool calling and JSON output on 17 Sep 2026). Model IDs configurable. Key supplied by the team in `backend/.env`. |
| Outgoing email | **Drafts only.** The app writes, approves and exports drafts; a person sends them and marks them sent. Gmail access stays read-only. |
| ML training data | **Real data: USAID SCMS Delivery History** (details in §6). |
| Google Drive | **Not built.** POs download as PDF. |

---

## 1. Approach

**Chosen — our provider abstraction + LangGraph state graphs over the existing services.**
OpenRouter is called through the existing `AIProvider` layer (extended with tool calling).
LangGraph orchestrates three graphs whose nodes call services that already exist or are
added in Phase 4. Scoring remains deterministic Python.

Alternatives considered:

- **LangChain chat models + LangGraph prebuilt agents** (`ChatOpenAI` pointed at OpenRouter,
  `create_react_agent`). Less custom code, but it introduces a second LLM abstraction beside
  `AIProvider`, pulls in `openai`/`tiktoken`/`langchain-core`, and fake models don't support
  tool binding, which makes the agent untestable without a key. Rejected.
- **No LangGraph, plain async orchestration.** Simplest, but drops a named synopsis
  technology and weakens the "multi-agent" claim in the project title. Rejected.

## 2. LLM layer

- `OpenAICompatibleProvider` — one class for OpenRouter and Ollama (OpenAI-compatible
  `/chat/completions`), selected by `AI_PROVIDER=openrouter|ollama|gemini|none`.
- Adds `chat(messages, tools) -> ChatResult(content, tool_calls)` to the `AIProvider`
  interface alongside the existing `generate()`. Gemini keeps `generate()` only; tool use
  requires an OpenAI-compatible provider.
- OpenRouter specifics: `models` array for native fallback routing; `HTTP-Referer` and
  `X-Title` headers; `response_format: {"type": "json_object"}` for extraction.
- **Rate limits and outages degrade, never crash:** HTTP 429/5xx → `AIResponse(ok=False)`
  → existing heuristic extraction, computed explanation, or template drafts, with the reason
  shown to the user.
- Env: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`,
  `OPENROUTER_FALLBACK_MODELS`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`.

## 3. Phase 3 — Gmail ingestion

Unchanged from the Phase 3 plan draft, with sending removed:

- Google OAuth 2.0, scope `gmail.readonly` only. Signed, 10-minute `state` binds the
  callback to organization and user. The session guard rejects any token whose `type` is
  not `access`, so a leaked `state` can't be used as a login.
- Refresh token encrypted at rest (Fernet; `TOKEN_ENCRYPTION_KEY`, derived from the JWT
  secret when unset). Never returned by the API.
- Plain `httpx` Gmail client with an injectable transport.
- Sync: messages matching `GMAIL_SYNC_QUERY` (default: last 30 days, subject contains
  quotation / quote / RFQ / price list / proforma / rate list). Each supported, non-inline
  attachment — or, if none, a quotation-like plain-text body — goes through
  `ingest_document_once()`. Dedup key `gmail:<messageId>:<partId>` (attachment IDs are not
  stable), backed by a unique partial index. Mail sent from the connected mailbox is skipped.
  Sender email links the quotation to a known supplier.
- Revoked or expired grant → connection `reauthorization_required`, HTTP 409 (never 401).
- Automatic sync every `GMAIL_SYNC_INTERVAL_MINUTES` (default 15; 0 disables) via an
  in-process scheduler, active only when Google credentials are configured.
- Collection `channel_connections` (unique per organization + provider).
- UI: **Integrations** page — connect, sync now, disconnect, last result; WhatsApp card
  marked *Planned*.

## 4. Phase 4 — procurement automation

### Communications (RFQ and negotiation drafts)
Collection `communications`:
`kind` (`rfq` | `negotiation` | `purchase_order`), `status`
(`draft` → `approved` → `sent` | `cancelled`), `procurement_request_id`, `supplier_id`,
`quotation_id`, `purchase_order_id`, `to_email`, `subject`, `body`, `generated_by`
(`ai` | `template`), `provider`, `model`, `guardrail_findings[]`, `history[]`
(who changed what, when).

- **RFQ**: from a procurement request and chosen suppliers → one draft per supplier listing
  items, quantities, units, specifications, required-by date and response instructions.
- **Negotiation**: from a comparison row → asks for a target price (user-set, default 5%
  below the quote), faster delivery or longer credit where that supplier scored lowest.
  **Guardrail:** the draft must not name any other supplier or state any other supplier's
  figures. Checked after generation against the comparison's supplier names and amounts;
  a violating draft is replaced by the template and the finding is recorded.
- Editing is allowed only in `draft`. `approve` records approver and time. `mark-sent`
  requires `approved` and records who sent it and when. Export as `.eml` (opens in any mail
  client) or copy.
- LLM writes the body; the template version is used when no LLM is available or the
  guardrail fails. `generated_by` always says which.

### Purchase orders
Collection `purchase_orders`:
`po_number` (`PO-<year>-<0001>`, per-organization atomic counter in `counters`),
`procurement_request_id`, `quotation_id`, `supplier_id`, `supplier` snapshot, `buyer`
snapshot, `lines[]` (request item, description, quantity, unit, unit price, tax %, line
total), `pricing` (subtotal, tax split, freight, total, currency), `terms` (delivery days,
payment terms), `status` (`draft` → `approved` → `issued` → `delivered` → `closed`;
`cancelled` from draft/approved/issued), `expected_delivery_date` (set on issue),
`delivered_at`, `on_time`, `delay_days`, `history[]`.

- **Award** from the comparison: creates the PO draft from the quotation's effective data;
  lines come from matched items (requested quantity × quoted unit price). Unmatched request
  items are listed as warnings, not silently priced. Request status → `awarded`.
- **Tax split:** CGST + SGST when the buyer and supplier GSTIN state codes match, IGST when
  they differ, a single "GST" line when either GSTIN is unknown.
- **PDF** rendered with PyMuPDF (amounts written with "INR" to avoid font dependence).
- **Delivery recording** (`delivered_at`) computes `on_time` and `delay_days` — this is the
  real delivery history the Phase 6 reliability model uses.
- An approved PO produces a `purchase_order` communication draft (PDF linked) for
  sending.
- **Organization profile** gains address, GSTIN, state, contact email/phone, editable in
  a Settings page, used as the PO buyer block.

### Comparison changes
- Transportation cost shown as its own column.
- **Award** and **Draft negotiation** actions per row.

## 5. Phase 5 — multi-agent orchestration

Collection `agent_runs`: `graph`, `status`, `input`, `steps[]` (agent, action, summary,
started/finished, error), `output`, `organization_id`, `created_by`.
Every graph run is recorded step by step and shown as a timeline.

**Graph 1 — Quotation processing** (replaces the linear pipeline; same stages and outputs):
`Document Extraction Agent` (raw extraction → structured extraction → validation) →
`Normalization Agent` → `Supplier Resolution` → `Matching Agent` → `Finalize`.
Conditional edges: empty extraction → `fail`; validation errors → `requires_review`.
The Phase 2 end-to-end suite must still pass unchanged.

**Graph 2 — Sourcing** (per procurement request):
`Comparison Agent` (deterministic scoring) → `Recommendation Agent` (explanation) →
`Negotiation Agent` (drafts for the top-ranked supplier's weakest criteria) → **stop at
`awaiting_approval`**. Human approval happens through the communications workflow; the graph
never sends or approves anything itself.

**Graph 3 — Procurement Assistant** (chat):
agent node ↔ tool node loop, maximum 6 tool rounds. Tools, all bound server-side to the
caller's organization (never taken from model output):
`list_procurement_requests`, `get_procurement_request`, `search_quotations`,
`get_quotation`, `get_comparison`, `get_supplier`, `spend_summary`,
`draft_rfq` (creates a draft only), `draft_negotiation` (creates a draft only).
System prompt requires answers grounded in tool results and forbids inventing figures.
Collection `conversations` stores messages including tool calls. Without an LLM the endpoint
returns 503 with the configuration reason.

UI: **Assistant** chat page (tool calls shown as collapsible steps, links to referenced
records); **agent run timeline** on request and quotation pages; **Run sourcing agents**
button on the comparison page.

## 6. Phase 6 — machine learning analytics

### Dataset
**USAID Supply Chain Management System (SCMS) Delivery History** — 10,324 real health-
commodity shipments, 33 columns, 73 vendors (incl. SCMS's own warehouse), 43 countries,
scheduled and actual delivery dates, 2006–2015.

- Provenance: published by USAID on data.usaid.gov (dataset `a3rc-nmf6`). The official
  portal and data.world mirror are offline as of Sep 2026. The copy used is the raw file from
  `github.com/jrcinco/supply-chain-shipment-price-data`
  (SHA-256 `918b992dd3e8d4b64d2a727b2c4ea607603d0c58f19484e73f7b78528c6a8673`), cross-checked against an independent cleaned mirror
  (`github.com/Prashant-Abbi/Supply-Chain-Management`): identical shipment IDs, scheduled,
  delivered and recorded dates, weights, freight costs and late-delivery labels.
- US federal government data. Stored at `backend/ml/data/` with a README recording source,
  checksum and verification.
- Facts: 11.5% of all shipments late; 5.3% of the 4,920 external-vendor shipments late;
  late rate varies 0–12% by year.

### Model 1 — supplier late-delivery risk (reliability prediction)
- **Label:** delivered after the scheduled date. Observed after the order, never an input.
- **Rows:** all 10,324 shipments (warehouse and direct). Metrics are also reported for
  the 4,920 external-vendor shipments on their own.
- **Features — only what is known when an order is placed, and only what any
  organization's own PO history can also provide** (so the model transfers to the app):
  supplier's prior shipment count, prior on-time rate, prior mean delay, late rate over the
  last 10 shipments, days since the supplier's previous shipment (all computed strictly from
  *earlier* shipments), order value (log), quantity (log), shipment mode, whether the order
  is fulfilled from a warehouse or direct (both recorded as "unknown" when an
  organization's POs don't capture them). Excluded: actual dates, delivery-recorded date,
  freight and insurance (known only afterwards), country and product (domain-specific).
- **Evaluation:** time-ordered split — train 2006–2013, test 2014–2015 — plus 5-fold
  cross-validation on the training period. Reported: ROC-AUC, PR-AUC, macro-F1, Brier score,
  against two baselines (always "on time"; supplier's prior on-time rate alone).
- **Candidates:** logistic regression, random forest, histogram gradient boosting
  (scikit-learn), class-weighted. Winner chosen by cross-validated PR-AUC.
- **Artifact:** `backend/ml/artifacts/reliability_model.joblib` + `.json` metadata
  (version, feature list, training window, metrics, baselines, scikit-learn version,
  dataset checksum). Training is reproducible via `backend/ml/train_reliability.py`.
- **In the app:** supplier reliability shows `method: "ml_model"`, the late-delivery
  probability, model version and "trained on USAID SCMS 2006–2013" when the supplier has
  delivery history; the rule-based score remains the fallback and is shown alongside. The
  model's reported metrics are shown honestly, whatever they turn out to be.
- **Retraining on own data:** `POST /analytics/models/reliability/retrain` trains on the
  organization's delivered POs when at least 50 exist, otherwise explains why not.

### Model 2 — price anomaly detection
- Isolation Forest per product (normalized name) on log unit price relative to the
  product's median, plus log quantity. Used when a product has ≥ 20 price observations;
  otherwise the existing Z-score or "insufficient data". Output states the method.
- Offline evaluation on SCMS (86 products): no ground-truth labels exist, so the report
  shows flagged shares and examples rather than an accuracy figure.

### Spend analytics
`GET /analytics/spend`: spend by supplier, by month and by item from issued/delivered POs;
quoted-versus-awarded savings per request; on-time delivery rate per supplier.
**Analytics** page with charts.

### Demand forecasting (stretch)
Monthly quantity per item from PO history; seasonal-naive and linear-trend forecasts,
backtested on SCMS product groups (MAPE reported). In-app forecasts require ≥ 12 months of
history; otherwise "insufficient data".

### Real-data demo organization
`backend/ml/load_scms_demo.py` creates a demo organization whose suppliers, delivered
purchase orders and price history come from the SCMS file, so reliability predictions,
anomalies, spend and forecasts can be shown on real data inside the app. Currency USD.
Clearly named "SCMS demo — USAID public data".

### Notebook
The team notebook's workflow (model comparison, saved artifacts) is kept; its circular
target, sales-based features and missing baseline are not carried over. Its original code
and CSVs are not available on this machine.

## 7. Cross-cutting

- **Architecture rules kept:** MongoDB only in repositories; organization scoping on every
  query; raw and machine-produced data never overwritten.
- **New dependencies:** `langgraph`, `scikit-learn`, `joblib`, `cryptography` (pinned).
- **Testing:** new pytest suite (`backend/tests/`) against a throwaway MongoDB database with
  a fake Google transport and a scripted fake LLM provider; the existing 120-assertion
  end-to-end script extended to Phases 3–6; ML evaluation report produced by the training
  script; browser check of every new page.
- **Error handling:** LLM 429/5xx → fallback with visible reason; guardrail failure →
  template; Gmail revoked → reconnect; missing model artifact → rule-based; illegal status
  transitions → 409.
- **New pages:** Integrations, Communications, Purchase Orders, Assistant, Analytics,
  Settings.

## 8. Out of scope

Sending email from the app; Google Drive; WhatsApp (remains future work); LlamaParse;
XGBoost (scikit-learn models are sufficient and match the synopsis stack).

## 9. What the team must supply

| Item | Needed for | Without it |
|---|---|---|
| `OPENROUTER_API_KEY` | Live AI extraction, drafts, agents, chat | Heuristic extraction, template drafts, chat unavailable |
| Google OAuth client (ID + secret) | Live Gmail connection | Gmail verified only against simulated Google responses |
