# Handoff — 17 Sep 2026

## 1. Goal
Build the Autonomous Procurement Assistant (VIT group SY-K10, `Synopsis.pdf`) through
**Phase 6**. That covers Gmail ingestion, RFQ/negotiation/PO drafts, LangGraph multi-agent
orchestration and scikit-learn ML trained on real data. The LLM is **OpenRouter with free
models**. Build everything first, then make **one commit** (team instruction).
Source of truth: `docs/superpowers/specs/2026-09-17-phases-3-6-design.md`.

## 2. Current state
- **Phases 1–2:** done (FastAPI + MongoDB + React). The earlier 120-assertion E2E script
  (`backend/scripts/test_e2e.py`) has not been re-run since this session's changes.
- **Phase 3 (Gmail) backend:** done — plan tasks P3.1–P3.6.
- **Phase 4:**
  - Done: P4.1 OpenRouter provider, P4.2 organization profile.
  - Not started: P4.3 communications, P4.4 purchase orders, P4.5 comparison transport-cost
    column, P4.6 UI.
- **Phase 5:** not started.
- **Phase 6:**
  - A background agent was building `backend/ml/` from its own plan; it had not reported
    when this session ended.
  - Its files and artifacts exist (`reliability_model.joblib/.json`,
    `evaluation_report.md`); `analytics_evaluation.md` was not yet present.
  - The app-side integration (P6.1–P6.5) is not started.
- **Frontend:** nothing added for Phases 3–6. All new pages are deferred to one pass
  (Integrations, Communications, Purchase Orders, Settings, Assistant, Analytics).
- **Tests:** `pytest --ignore-glob="tests/test_ml_*"` → **85 passed** (161 s).
  - Setup takes ~7–8 s per test, possibly because the ML agent was training at the same
    time; not investigated.
  - The ML tests were not run by me.
- **Git:**
  - `master` has one baseline commit (`52f9cb8`).
  - All work since is **uncommitted** on branch `feature/phases-3-6`.
- **Config:**
  - `backend/.env` has `AI_PROVIDER=openrouter` with **`OPENROUTER_API_KEY` empty**.
  - The Google OAuth client ID and secret are empty.
- **Services:** MongoDB was started this session. Backend and frontend are not running.

## 3. Active files
- Plans:
  - `docs/superpowers/plans/2026-09-17-phases-3-5-and-integration.md` — my tasks
  - `docs/superpowers/plans/2026-09-17-phase6-ml-pipeline.md` — ML agent's tasks, with full tests
- Spec and roadmap: `docs/superpowers/specs/2026-09-17-phases-3-6-design.md`, `docs/ROADMAP.md`
- Backend (new): `app/core/{crypto,gstin}.py`, `app/api/routes/{channels,organizations}.py`,
  `app/services/channels/gmail_sync.py`, `app/integrations/ingestion/gmail_client.py`,
  `app/integrations/ai/openai_compatible.py`, `app/repositories/channels.py`,
  `app/workers/channel_scheduler.py`
- ML: `backend/ml/*`, `backend/ml/data/SCMS_Delivery_History_Dataset.csv`
- Tests: `backend/pytest.ini`, `backend/tests/conftest.py`,
  `backend/tests/fakes/{google,llm}.py`, `backend/tests/test_*.py`

## 4. Changes made
- **Docs:**
  - Roadmap re-aligned to the synopsis, including the notebook review.
  - Design spec and two plans written.
  - `git init`; `.gitignore` excludes `Synopsis.pdf` and `ff_180 format.docx` (phone numbers).
- **Dependencies:** pinned `cryptography 50.0.1`, `langgraph 1.2.11`, `scikit-learn 1.9.1`,
  `joblib 1.6.0`, `numpy 2.5.2` (numpy was upgraded; extraction re-verified 5/5).
- **Dataset:** USAID SCMS Delivery History (10,324 rows).
  - Official sources are offline, so it came from a GitHub mirror.
  - SHA-256 `918b992d…6c8a8673`.
  - Cross-checked against a second mirror: dates, weights, freight and late labels identical.
- **Ingestion:** `ingest_document_once()` deduplicates on an external reference, backed by a
  unique partial index. `.txt` uploads are now allowed. Repositories turn
  `DuplicateKeyError` into `ConflictError`.
- **Security:**
  - Fernet encryption for refresh tokens.
  - Signed 10-minute OAuth `state`.
  - **Sessions now reject any JWT whose `type` isn't `access`**, so an OAuth state can't be
    used to log in.
- **Gmail:** httpx client; sync of attachments plus quotation-like email bodies; dedup key
  `gmail:<msg>:<partId>`. Revoked access returns 409 and marks the connection as needing a
  reconnect. Scheduler wired into the app lifespan. `GET/…/channels` routes.
- **LLM:**
  - `ChatMessage`/`ToolCall`/`ChatResult` and `AIProvider.chat()` added.
  - `OpenAICompatibleProvider` serves OpenRouter (with a fallback model list) and Ollama.
  - Rate-limit, credit and timeout failures return an explained failure, never an exception.
  - Factory supports `openrouter|ollama|gemini|none`.
- **Bugs fixed:**
  - The GSTIN pattern rejected valid checksum digits, so Maruti's GSTIN was missed; now one
    shared `app/core/gstin.py`.
  - The 422 handler crashed with a 500 on custom-validator errors.
  - WhatsApp's `ingest_all` would have collided with the new unique index.
- **New endpoint:** `GET/PUT /organizations/me` (address, GSTIN, derived state, contacts).

## 5. Failed attempts (don't repeat)
- **Tesseract install:** needs admin rights. Use RapidOCR locally; Docker installs Tesseract.
- **Dataset sources that no longer work:**
  - `data.usaid.gov` and the `2012-2017.usaid.gov` archive are unreachable.
  - The data.world copy is gone (its open-data community retired in July 2026).
  - The Internet Archive was offline or returning 429.
  - The notebook's own code and CSVs aren't on this machine.
- **Bash heredocs with Python inside:**
  - Apostrophes can break the shell parse.
  - `\b`/`\n` escapes got mangled into real control characters; a stray backspace byte
    silently broke a regex.
  - → Write code with the Write/Edit tools. For control bytes use `bytes([..])`.
  - Clear `__pycache__` if a fix doesn't seem to take.
- **pydantic-settings:** `List[str]` fields fail to parse from `.env` — keep them as `str`.
- **Test emails:** `email-validator` rejects `.test` domains — use `.com`.
- **Vite dev server:** binds IPv6 only — use `localhost:5173`, not `127.0.0.1`.
- **Browser pane:** screenshots fail while it's hidden — use `get_page_text` or JS.
  Radix tab panels: find them by the trigger's `aria-controls` id.

## 6. Next steps
1. **Start MongoDB:**
   `C:/mongo-bin/mongod-x64-win32-7.0.14.exe --dbpath C:/mongo-data/db --port 27017 --bind_ip 127.0.0.1 --logpath C:/mongo-data/log/mongod.log --logappend`
2. **Check the ML package:** from `backend/`, run
   `./.venv/Scripts/python.exe -m pytest tests/test_ml_*.py -q --noconftest`.
   - Finish any failing task from the ML plan (Task 6's `analytics_evaluation.md` may be
     missing).
   - Read `ml/artifacts/evaluation_report.md` and report the metrics honestly.
3. **Continue the plan at P4.3** (communications: RFQ and negotiation drafts, guardrail,
   draft → approved → sent, `.eml` export), then P4.4 (purchase orders, PDF, delivery
   recording) and P4.5.
4. **Phase 5:** P5.1–P5.4 (agent runs, processing/sourcing graphs, assistant with
   org-bound tools). Test with `tests/fakes/llm.py`.
5. **Phase 6 integration:** P6.1–P6.4 (ML reliability from delivered POs, Isolation Forest
   anomalies, spend and forecast APIs, `scripts/load_scms_demo.py`).
6. **One frontend pass** for all new pages; then `tsc` + `vite build` + browser check.
7. **Final verification:**
   - Full pytest.
   - Re-run and extend `scripts/test_e2e.py`.
   - Look into the slow test setup.
   - Update README, ROADMAP status and memory.
8. **Commit once** on `feature/phases-3-6`, then use finishing-a-development-branch.
9. **The team adds** `OPENROUTER_API_KEY` (and the Google OAuth client) to `backend/.env`,
   restarts the backend, and verifies live AI and Gmail.
