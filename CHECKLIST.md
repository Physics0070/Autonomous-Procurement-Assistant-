# Build checklist — Phases 3–6

Updated after every task. ✅ done · 🔄 in progress · ⬜ not started · ⚠️ blocked/needs team

| # | Task | Status | Evidence / notes |
|---|---|---|---|
| 1 | MongoDB running | ✅ | `mongod` on 127.0.0.1:27017 |
| 2 | Phase 3 — Gmail ingestion backend (P3.1–P3.6) | ✅ | previous session; in pytest suite |
| 3 | Phase 4 — OpenRouter provider (P4.1), org profile (P4.2) | ✅ | previous session; in pytest suite |
| 4 | Phase 6 — ML package (`backend/ml/`) | ✅ | 32/32 ML tests pass; RF test ROC-AUC 0.83, PR-AUC 0.33 (baseline 0.25) |
| 5 | P4.5 Transport cost column in comparison | ✅ | `transport_cost` on each comparison row |
| 6 | P4.3 Communications — RFQ/negotiation drafts, guardrail, draft→approved→sent, `.eml` | ✅ | `tests/test_communications.py` 8 passed |
| 7 | P4.4 Purchase orders — award, CGST/SGST/IGST, lifecycle, delivery, PDF | ✅ | `tests/test_purchase_orders.py` 6 passed |
| 8 | P5.1–P5.2 Agent runs + LangGraph processing graph | ✅ | `tests/test_processing_graph.py` 2 passed |
| 9 | P5.3 Sourcing graph (stops at awaiting approval) | ✅ | `tests/test_sourcing_graph.py` 3 passed |
| 10 | P5.4 Procurement Assistant (tool loop, org-bound tools, 6-round limit) | ✅ | `tests/test_assistant.py` 5 passed |
| 11 | P6.3 Spend service | ✅ | used by assistant and Analytics API |
| 12 | P6.1 ML reliability from delivered POs + retrain endpoint | ✅ | `reliability.ml` on suppliers; retrain needs ≥ 50 delivered POs |
| 13 | P6.2 Isolation Forest price anomalies (≥ 20 prices) | ✅ | fixed: out-of-range prices now caught (Tukey fence); report regenerated |
| 14 | P6.3 Analytics API — spend, forecast, models | ✅ | `tests/test_analytics.py` 3 passed |
| 15 | P6.4 SCMS real-data demo organization loader | ✅ | 73 suppliers, 10,324 POs, 10,306 prices; login `scms.demo@procurement-demo.com` (password set via `SCMS_DEMO_PASSWORD`) |
| 16 | Frontend — Integrations, Communications, Purchase Orders, Settings, Assistant, Analytics | ✅ | + Award/Negotiate/Run agents on comparison, Draft RFQs, agent timelines, ML badge; all pages browser-checked |
| 16b | Hardcoding review | ✅ | tunables → settings; placeholder JWT secret refused outside dev; `.env` anchored; compose/env examples → OpenRouter; demo creds env-overridable |
| 17 | Final verification — full pytest, E2E script, `tsc` + `vite build`, browser check | ✅ | pytest 144 passed · E2E 147/147 · tsc + build clean · pages checked |
| 18 | Docs — README, ROADMAP status, handoff | ✅ | ROADMAP: 15/15 synopsis features done |
| 19 | Commit on `feature/phases-3-6` | ✅ | local only, not pushed; merge target (`master` vs `main`) awaits the team |
| 20 | Team adds `OPENROUTER_API_KEY` + Google OAuth client, verifies live | ⚠️ | needs the team |
| – | `/graphify` knowledge graph of the repo | ⏸️ | stopped on request; unlabeled graph in `graphify-out/` (git-ignored) |

## Multi-agent upgrade (20 Sep 2026)

| # | Task | Status | Evidence / notes |
|---|---|---|---|
| A1 | Shared agent loop (assistant + specialists on one LangGraph loop) | ✅ | `services/agents/loop.py` |
| A2 | Supervisor agent routes each turn (LLM, bounded by policy) | ✅ | `tests/test_supervisor.py` — illegal model choices fall back to policy |
| A3 | Handoffs between agents (`Command(goto=...)`) | ✅ | supervisor ↔ 5 specialists |
| A4 | Durable pause/resume for approval + step budget | ✅ | state in `agent_runs`; resume after approval creates the PO |
| B1 | Negotiation Agent with retrieval (performance, price history, past negotiations) | ✅ | guardrail tool rejects leaks; agent rewrites |
| B2 | Critic Agent reviews drafts; deterministic guardrail stays the hard gate | ✅ | rejection falls back to template |
| B3 | Risk Agent (ML) consulted before ordering | ✅ | raises a concern → negotiate first |
| C1 | Monitor Agent starts sourcing when quotations arrive | ✅ | `tests/test_monitor_agent.py` |
| C2 | Watchdog drafts follow-ups for overdue deliveries | ✅ | one draft per order, never repeated |
| D1 | Extraction Agent self-corrects using validator feedback | ✅ | re-reads once, keeps the better result |
| E1 | Backend regression | ✅ | **158 passed** |
| E2 | Frontend for supervisor runs (reasoning + resume) | ✅ | timeline shows routing reasons; Continue/Stop resume the run — verified in the browser |
| E3 | Docs, E2E extension, commit and push | ✅ | E2E **155/155**; README agent table; pushed to `main` |

## Synopsis completion + ML strengthening (20 Sep 2026)

| # | Task | Status | Evidence / notes |
|---|---|---|---|
| F1 | ML: probability calibration | ✅ | Brier 0.167 → **0.099**, now better than both baselines |
| F2 | ML: precision/recall reported, plus a screening operating point | ✅ | shipped 0.36/0.55; screening 0.32/0.92 |
| F3 | ML: date-based split so an org can retrain on a short history | ✅ | `train_end_date` |
| G1 | Google Drive upload for purchase orders (last unbuilt stack item) | ✅ | `tests/test_drive.py` 6 tests; "Save to Drive" on the PO page |
| G2 | Delivery **dates** extracted, not just lead days | ✅ | `tests/test_delivery_dates.py` 8 tests; sets the PO's expected date |
| G3 | Verification | ✅ | pytest **172 passed**; E2E **156/156**; tsc + build clean |
| G4 | Placeholders where credentials are missing | ⚠️ | Drive/Gmail → 503 naming the missing setting; AI → template fallback |

## Security + LLM council (21 Sep 2026)

| # | Task | Status | Evidence / notes |
|---|---|---|---|
| S1 | GitHub secret audit | ✅ | no API key ever committed (tracked files + full history scanned) |
| S2 | JWT placeholder guard bypass fixed | ✅ | the `.env.example` placeholder used to pass in production; `tests/test_config_secrets.py` |
| S3 | Published demo password removed and rotated | ✅ | loader generates a random one unless `SCMS_DEMO_PASSWORD` is set |
| C1 | A different model per task (`LLM_TASK_MODELS`) | ✅ | 8 tasks; unlisted tasks use the default model |
| C2 | LLM council: answer → anonymous peer review → monitor decides | ✅ | `CouncilProvider`; failing members dropped; transcript kept |
| C3 | Council wired into real agent runs | ✅ | e.g. council as Critic rejects a draft in a full supervisor run |
| C4 | API key placeholders | ⚠️ | `OPENROUTER_API_KEY`, `LLM_TASK_MODELS`, `COUNCIL_MODELS`, `COUNCIL_MONITOR_MODEL` await your values |
| I1 | Official Indian data: GST HSN master (21,935 codes) | ✅ | `ml/data/india/`; found a data error in the official file (8539) |
| I2 | Indian benchmark: 114 quotation-style items, 29 dev / 85 held-out test | ✅ | labels checked against the master |
| I3 | HSN suggestion: text shortlist + checked model decision | ✅ | `tests/test_ml_hsn.py` 9 tests; `GET /analytics/hsn` |
| I4 | Held-out accuracy | ⚠️ | text alone **54.1%** top-1; right answer on shortlist **97.6%**; model stage **not yet measured (needs key)** — `python -m ml.hsn test --llm` |

## Reporting decision (22 Sep 2026)

| # | Task | Status | Evidence / notes |
|---|---|---|---|
| R1 | USAID dataset is the headline ML result | ✅ | README leads with ROC-AUC 0.83 on 2,545 unseen shipments; HSN marked supplementary until its model stage is measured |


## Direct AI vendors + review prep (23 Sep 2026)

| # | Task | Status | Evidence / notes |
|---|---|---|---|
| V1 | Direct vendors (Gemini, Grok, Qwen, Ollama) usable at once via `vendor:model` | ✅ | `tests/test_vendors.py` 6 tests; Gemini SDK removed (one HTTPX client for all) |
| V2 | Full regression | ✅ | pytest **204 passed** (MongoDB must be running) |
| V3 | Key placeholders in `backend/.env` | ⚠️ | `GROK_API_KEY`, `QWEN_API_KEY` await your values; `GEMINI_API_KEY` has a value, and a live call returned 404 "model not found", to be checked when the keys land |
| V4 | Mid-sem review sheet (stack, full forms, all parameters) | ✅ | published as a private artifact |
| V5 | Live council + HSN-with-LLM measurement | ⬜ | runs as soon as the keys are in |
