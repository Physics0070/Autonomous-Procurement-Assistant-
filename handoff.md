# Handoff — 20 Sep 2026

## 1. Goal
Autonomous Procurement Assistant (VIT SY-K10, `Synopsis.pdf`) through **Phase 6**. Spec:
`docs/superpowers/specs/2026-09-17-phases-3-6-design.md`. Progress table: `CHECKLIST.md`.

## 2. State — everything built and verified
- **Backend:** Phases 1–6 plus the multi-agent upgrade. `pytest -q` from `backend/` → **158 passed**, ~3 min.
- **End-to-end:** `scripts/test_e2e.py` against the live API → **155/155**.
- **Multi-agent:** a Supervisor Agent routes 5 specialists (comparison, recommendation, risk,
  negotiation, purchase order) with `Command` handoffs; runs pause for approval and resume from
  state stored in `agent_runs`; a Monitor Agent starts sourcing when quotations arrive and chases
  overdue deliveries; the Negotiation Agent researches before drafting and a Critic reviews it;
  the Extraction Agent re-reads a document once when validation finds errors.
  Bounds: the supervisor may only pick actions the policy allows, `AGENT_MAX_STEPS` caps a run,
  and nothing is ever sent.
- **Frontend:** new pages Communications, Purchase orders, Assistant, Analytics, Integrations,
  Settings; comparison has Transport column, Award / Negotiate per row, Run agents (supervisor);
  request page has Draft RFQs; agent-run timelines on request, comparison and quotation pages;
  ML risk badge on Suppliers. `tsc -b` + `vite build` clean; every page checked in the browser.
- **ML:** random forest late-delivery model (test ROC-AUC 0.83, PR-AUC 0.33 vs 0.25 baseline,
  accuracy 77.4% vs 86.0% always-on-time). Isolation Forest anomalies (with a Tukey-fence fix
  for out-of-range prices). Forecasts. Reports in `backend/ml/artifacts/`.
- **Demo data:** `python -m scripts.load_scms_demo` → org "SCMS demo — USAID public data",
  `scms.demo@procurement-demo.com` / `ScmsDemo2026!` (73 suppliers, 10,324 POs). Loaded in the dev DB.
- **Git:** single branch `main`, pushed to github.com/Physics0070/Autonomous-Procurement-Assistant-

## 3. Agent design notes
- LangGraph's MongoDB checkpointer needs pymongo ≥ 4.12 but Motor pins < 4.10, so runs persist
  their own state in `agent_runs` instead. Do not install `langgraph-checkpoint-mongodb`.
- Tests drive the agents with `tests/fakes/llm.py`. Several agents call `generate()` in one run,
  so answer by *which agent is asking* (`ScriptedProvider(responder=...)`), not by queue order.

## 4. Fixed this session (worth knowing)
- `Settings` read `.env` relative to the working directory → now anchored to `backend/`.
- The app refuses the placeholder `JWT_SECRET_KEY` outside `ENVIRONMENT=development`.
- Repository lists cap at 500 → analytics use `PurchaseOrderRepository.find_all`.
- Supplier list scored the forest once per supplier (7.6 s) → batch `predict_many` (~2 s on 10k POs).
- "Original" file link had no auth header (401) → `downloadFile()` helper fetches with the token.
- `scrollIntoView` returns a Promise in current Chrome → effects must use a block body.
- docker-compose / root `.env.example` still targeted Gemini → OpenRouter + Google vars.

## 5. Needs the team
1. `OPENROUTER_API_KEY` in `backend/.env` (live extraction, AI drafts, assistant).
2. Google OAuth client ID/secret; redirect URI `http://localhost:8000/api/v1/channels/gmail/callback`;
   add the Gmail account as a test user.
3. Nothing else — `main` is pushed and up to date.

## 6. Gotchas (don't repeat)
- Tesseract needs admin — RapidOCR locally, Docker installs Tesseract.
- Python in bash heredocs: `\n` escapes get mangled — use the Write/Edit tools for code with escapes.
- `pydantic-settings` `List[str]` from `.env` fails — keep as comma-separated `str`.
- `email-validator` rejects `.test` domains — use `.com`.
- Vite binds IPv6 — use `localhost:5173`.
- Browser pane screenshots fail when hidden — use `get_page_text`.
- MongoDB: `C:/mongo-bin/mongod-x64-win32-7.0.14.exe --dbpath C:/mongo-data/db --port 27017 --bind_ip 127.0.0.1`.
- Servers: `.claude/launch.json` (`backend`, `frontend`).
