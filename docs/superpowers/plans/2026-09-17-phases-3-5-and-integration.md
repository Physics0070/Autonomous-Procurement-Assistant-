# Phases 3–5 and Phase 6 Integration — Implementation Plan

> **For agentic workers:** executed inline with anthropic-skills:executing-plans,
> anthropic-skills:test-driven-development and anthropic-skills:verification-before-completion.
> Deliberate deviation from the plan template, requested by the team ("optimise work"):
> this plan fixes files, interfaces and test cases; code is written test-first during the
> build instead of being duplicated here. The Phase 6 ML pipeline has its own full plan
> (`2026-09-17-phase6-ml-pipeline.md`) because a separate agent builds it.

**Goal:** Deliver spec §2–§5 plus the in-app half of §6.
**Architecture:** see spec §1. Services stay framework-free; MongoDB only in repositories;
LangGraph orchestrates services; LLM calls only through `AIProvider`.
**Tech stack:** FastAPI, Motor, httpx, cryptography, LangGraph 1.2.11, PyMuPDF, React/TS.

## Global constraints
- Spec: `docs/superpowers/specs/2026-09-17-phases-3-6-design.md`.
- Gmail scope is `gmail.readonly` only. Nothing is ever emailed by the app.
- Every org-scoped query goes through `OrgScopedRepository._scope`.
- Raw/AI/normalized data are never overwritten.
- Google auth failures return 409, never 401.
- LLM failure never fails a request that has a deterministic or template fallback.
- Tests: `backend/tests/`, run with `./.venv/Scripts/python.exe -m pytest -q` from `backend/`.
- Do not edit `backend/ml/` or `tests/test_ml_*.py` (owned by the ML agent until it reports).
- **No git commits until everything is built** (team instruction); one commit at the end.

---

## Phase 3 — Gmail ingestion

### P3.1 Dedup-aware ingestion
- Modify `services/documents/detection.py`: `.txt` / `text/plain` accepted.
- Modify `repositories/base.py`: `create()` maps `DuplicateKeyError` → `ConflictError`.
- Modify `repositories/quotations.py`: `find_by_external_reference(org_id, ref) -> dict | None`.
- Modify `core/database.py`: unique partial index `(organization_id, source.external_reference)`
  where the reference is a string; unique `(organization_id, provider)` on `channel_connections`.
- Modify `services/documents/ingestion.py`:
  `ingest_document_once(payload, *, organization_id, uploaded_by, repository, storage) -> tuple[dict, bool]`.
- Tests `tests/test_ingestion_dedup.py`: txt accepted; same ref ingested once; refs scoped per
  org; ref required; DB rejects a racing duplicate with `ConflictError`.

### P3.2 Secrets and OAuth state
- Create `core/crypto.py`: `encrypt_secret(str) -> str`, `decrypt_secret(str) -> str`,
  `TokenDecryptionError`.
- Modify `core/security.py`: `create_oauth_state(*, organization_id, user_id, provider, ttl_minutes=10) -> str`,
  `verify_oauth_state(state, *, provider) -> dict`.
- Modify `api/deps.py`: reject tokens whose `type != "access"`.
- Modify `core/config.py` + `.env.example`: `TOKEN_ENCRYPTION_KEY`, `FRONTEND_URL`,
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `GMAIL_SCOPES`,
  `GMAIL_SYNC_QUERY`, `GMAIL_MAX_MESSAGES_PER_SYNC`, `GMAIL_SYNC_INTERVAL_MINUTES`;
  property `google_configured`.
- Tests `tests/test_security_tokens.py`: round trip without plaintext; tamper rejected;
  state round trip; wrong provider rejected; expired rejected; state unusable as a session.

### P3.3 Gmail client
- Create `integrations/ingestion/gmail_client.py`: `GmailClient(http)` with `exchange_code`,
  `refresh_access_token`, `revoke`, `get_profile_email`, `list_message_ids`, `get_message`,
  `get_attachment`; helpers `build_authorize_url`, `decode_base64url`, `header`,
  `parse_sender_email`, `iter_parts`, `extract_plain_body`; errors `GmailAPIError`,
  `GmailAuthError`; `TokenGrant`.
- Create `tests/fakes/google.py` (`FakeGoogle`, `FakeMessage`, `FakeAttachment`, `b64url`);
  attachment IDs rotate per fetch, like Gmail's.
- Add `google` fixture to `conftest.py`.
- Tests `tests/test_gmail_client.py`: consent URL; base64url; sender parsing; MIME walk;
  exchange → refresh → profile → list → message → attachment; revoked refresh → auth error;
  bad access token → auth error.

### P3.4 Sync service
- Create `repositories/channels.py`: `ChannelConnectionRepository` with `get_for_provider`,
  `upsert_for_provider`, `update_status`, `delete_for_provider`, `list_active(provider)`.
- Create `services/channels/gmail_sync.py`: `Enqueue`, `GmailSyncResult`,
  `sync_gmail(...) -> GmailSyncResult`.
- Modify `integrations/ingestion/channels.py`: drop the Gmail stub, keep WhatsApp.
- Tests `tests/test_gmail_sync.py`: imports PDF + XLSX + quotation body, ignores zip and
  inline logo, skips non-quotation mail; second sync imports nothing; known sender linked to
  supplier; own outgoing mail skipped; revoked grant raises.

### P3.5 Channel API
- Modify `core/errors.py`: `UpstreamError` (502).
- Append `run_gmail_sync(...) -> dict` to `gmail_sync.py`.
- Create `api/routes/channels.py`: `GET /channels`, `GET /channels/gmail/authorize`,
  `GET /channels/gmail/callback`, `POST /channels/gmail/sync`, `DELETE /channels/gmail`;
  dependencies `get_gmail_client`, `get_enqueue`. Add `channel_repo` to `deps.py`; register router.
- Tests `tests/test_channels_api.py`: 503 unconfigured; consent URL; forged state; connect
  stores encrypted token and never returns it; sync imports and records outcome; revoked →
  409 + reconnect state; disconnect revokes; org isolation.

### P3.6 Scheduler
- Create `workers/channel_scheduler.py`: `sync_all_gmail(*, database, client, storage, enqueue) -> dict`,
  `ChannelScheduler`, `get_channel_scheduler()`; start/stop in `main.py` lifespan.
- Tests `tests/test_channel_scheduler.py`: all connected orgs synced, revoked org marked;
  disabled without credentials; disabled at interval 0.

### P3.7 Integrations UI
- `types`, `hooks/queries.ts`, `pages/Integrations.tsx`, route + nav.
- Verify: `tsc`, `vite build`, browser.

## Phase 4 — Procurement automation

### P4.1 OpenAI-compatible provider
- Modify `integrations/ai/base.py`: `ChatMessage`, `ToolCall`, `ChatResult`;
  `AIProvider.chat(messages, *, tools=None, temperature=0.2, max_output_tokens=2048) -> ChatResult`
  (default: unsupported); `supports_tools` property.
- Create `integrations/ai/openai_compatible.py`: `OpenAICompatibleProvider(name, base_url,
  api_key, model, fallback_models, extra_headers, http=None)`; `generate()` and `chat()`;
  429/5xx/timeouts → `ok=False` with reason.
- Modify `factory.py`: `openrouter`, `ollama`, `gemini`, `none`; config
  `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`,
  `OPENROUTER_FALLBACK_MODELS`, `OPENROUTER_APP_URL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`.
- Create `tests/fakes/llm.py`: `ScriptedProvider` (queued `AIResponse`/`ChatResult`, records calls).
- Tests `tests/test_openai_provider.py`: request shape (model, fallback `models`, headers,
  `response_format`); JSON content returned; tool calls parsed; 429 → `ok=False` with reason;
  unconfigured factory → `UnconfiguredProvider`; extraction falls back on 429.

### P4.2 Organization profile
- Modify `schemas/auth.py`, `repositories/users.py`, `api/routes/auth.py`:
  `GET/PUT /organizations/me` with address, GSTIN (validated format), state, contact email/phone.
- Tests in `tests/test_organization_profile.py`.

### P4.3 Communications
- Create `schemas/communication.py`, `repositories/communications.py`,
  `services/automation/templates.py`, `services/automation/drafting.py`
  (`draft_rfqs`, `draft_negotiation`, `check_negotiation_guardrail`),
  `services/automation/communications.py` (`transition`, `to_eml`),
  `api/routes/communications.py`.
- Endpoints: `GET /communications`, `GET /communications/{id}`,
  `POST /procurement-requests/{id}/rfqs`, `POST /comparisons/procurement-requests/{id}/negotiations`,
  `PATCH /communications/{id}`, `POST /communications/{id}/approve`,
  `POST /communications/{id}/mark-sent`, `POST /communications/{id}/cancel`,
  `GET /communications/{id}/eml`.
- Tests `tests/test_communications.py`: template RFQ lists items; AI RFQ recorded as `ai`;
  AI failure → template with reason; guardrail catches competitor name and competitor total;
  status machine (edit only in draft; mark-sent needs approved; cancel rules → 409);
  `.eml` export; org isolation.

### P4.4 Purchase orders
- Create `schemas/purchase_order.py`, `repositories/purchase_orders.py` (+ `counters`),
  `services/automation/purchase_orders.py` (`award_quotation`, `tax_split`, `transition`,
  `record_delivery`), `services/automation/po_pdf.py` (`render_po_pdf`),
  `api/routes/purchase_orders.py`.
- Endpoints: `POST /comparisons/procurement-requests/{id}/award`, `GET /purchase-orders`,
  `GET /purchase-orders/{id}`, `POST /purchase-orders/{id}/approve|issue|deliver|close|cancel`,
  `GET /purchase-orders/{id}/pdf`.
- Approve creates a `purchase_order` communication draft.
- Tests `tests/test_purchase_orders.py`: sequential PO numbers per org; lines from matched
  items; unmatched items warned; CGST/SGST vs IGST vs GST; transitions; delivery → on_time /
  delay_days; PDF starts with `%PDF`; award sets request `awarded`; isolation.

### P4.5 Comparison additions
- Transport cost field on `SupplierScore`.

### P4.6 UI
- Pages: Communications (list, detail/edit/approve/mark sent/export), Purchase Orders (list,
  detail with lifecycle + delivery recording + PDF), Settings (organization profile);
  comparison Award / Draft negotiation; request page Draft RFQs.

## Phase 5 — Multi-agent orchestration

### P5.1 Agent runs
- `repositories/agent_runs.py`, `services/agents/runs.py` (`RunRecorder` with `step()` context).

### P5.2 Processing graph
- `services/agents/processing_graph.py`: LangGraph `StateGraph` with nodes
  `document_extraction`, `normalization`, `supplier_resolution`, `matching`, `finalize`, `fail`.
  `ProcessingPipeline.run` delegates to it; outputs unchanged.
- Tests `tests/test_processing_graph.py` + the existing E2E script unchanged.

### P5.3 Sourcing graph
- `services/agents/sourcing_graph.py`: `comparison` → `recommendation` → `negotiation` →
  `awaiting_approval`. Endpoint `POST /agents/sourcing/{request_id}`, `GET /agents/runs`,
  `GET /agents/runs/{id}`.
- Tests `tests/test_sourcing_graph.py`: steps recorded in order; drafts created in `draft`;
  nothing approved or sent.

### P5.4 Assistant
- `services/agents/assistant_tools.py`, `services/agents/assistant_graph.py`,
  `repositories/conversations.py`, `api/routes/assistant.py`
  (`POST /assistant/messages`, `GET /assistant/conversations`, `GET /assistant/conversations/{id}`).
- Tests `tests/test_assistant.py` with `ScriptedProvider`: tool loop executes and answers;
  tools are org-bound (a model-supplied org id is ignored); draft tool creates a draft only;
  tool-round limit; 503 without an LLM.

### P5.5 UI
- Assistant page; agent run timeline; "Run sourcing agents" button.

## Phase 6 — in-app integration (after the ML agent reports)

### P6.1 Reliability
- `services/analytics/reliability_ml.py`: supplier order history from delivered POs →
  `ReliabilityModel.predict_for_supplier`; combined with the rule-based score in
  `SupplierOut.reliability`; `POST /analytics/models/reliability/retrain` (≥ 50 delivered POs).

### P6.2 Anomalies
- `services/procurement/anomaly.py`: use `ml.anomaly.assess_price` when ≥ 20 observations.

### P6.3 Spend and forecasting
- `services/analytics/spend.py`, `api/routes/analytics.py`: `GET /analytics/spend`,
  `GET /analytics/forecast`, `GET /analytics/models`.

### P6.4 Real-data demo organization
- `ml/load_scms_demo.py` is **not** in `ml/` ownership conflict once the agent reports; create
  it as `backend/scripts/load_scms_demo.py` instead.

### P6.5 UI
- Analytics page; ML reliability on the Suppliers page.

## Final verification
- Full pytest suite; `scripts/test_e2e.py` extended; browser walkthrough of every page;
  README, ROADMAP status, build register; single commit.
