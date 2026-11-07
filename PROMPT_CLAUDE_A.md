You are Claude A (BUSINESS) in a 2-session hackathon team. The repo is C:\Users\Aziz\louben, on branch `claude-a/business`.

FIRST: read PLAN.md completely. It is the contract with Claude B (TRUST), who works in parallel. Follow it exactly.

YOUR #1 PRIORITY IS THE VISIBLE DEMO (PLAN.md Section 0): voice conversation with the agent, live agent collaboration graph, interactive dashboard where every KPI is clickable, knowledge graph. Build a thin working slice first, polish later. `main` must always run the demo.

## Hard rules
1. Only edit files that PLAN.md Section 5 assigns to A. Never touch B's files after CP0.
2. Never change a model in `common/schemas.py` after CP0, except adding optional fields logged in the PLAN.md changelog.
3. Every LLM call goes through `common/llm.py` and has a deterministic fallback. The demo must work offline.
4. Fake data only. No real names, emails, card numbers or secrets in code or logs. Secrets live in `.env`.
5. Commit after every task with prefix `[A]`. Merge at each checkpoint following PLAN.md Section 12.
6. Windows machine: use `py`/`python` and PowerShell compatible commands.
7. If you need something from B, write it in `notes/a_to_b.md` and tell me.

## Phase 0 (start now, done by 00:30): skeleton for BOTH sides
Build the full skeleton so both sessions can run the whole system from minute one:
1. Layout from PLAN.md Section 5, `.gitignore` (keys/, data/*.db, .env, .venv), `.env.example`, requirements files.
2. `common/`: `config.py`, `schemas.py` (all models of Section 7), `a2a.py` (Section 6: `create_agent_app`, `call`, retries + timeout + clear errors), `llm.py`, `events.py`.
3. Simple first versions of B's files (they take over at CP0): `common/crypto.py` (Ed25519 keygen, sign/verify bytes, JWT sign/verify, card sign/verify), `common/audit.py` (append + list, hash chain can be basic), `scripts/gen_keys.py`, `config/acl.json`, `config/policy.json`, `hub/routes_trust.py` (endpoints returning fake data), `hub/static/trust.js` (renders placeholders).
4. Stub `main.py` for all 8 agents + gate: each exposes its card and its skills from Section 8 returning realistic fake data that matches the schemas.
5. `hub/main.py` (events endpoint, SSE `/stream`, static files, `/demo` and `/dashboard` routes, includes both routers), `hub/static/index.html` with all panel ids of Section 10, `demo.html` (Section 0 layout), `style.css`, `client.html`, and a first `graph.js` that draws the 8 agent nodes and animates an edge on every `a2a.call` event. `common/a2a.py` must emit `a2a.call` on every call (success, refusal or error).
6. `scripts/run_all.py` (generates keys if missing, starts all services, Ctrl+C stops all) and `scripts/smoke_test.py` (calls each skill once, then imports and runs `smoke_a.run()` and `smoke_b.run()` if they exist).
7. `config/catalog.json`: 6 AI training courses (fake), prices between 300 and 1500 TND.
8. Run it, fix it, merge to main, tell me "CP0 done" so Claude B can pull.

## Demo UI (build right after CP0, must work at CP1 02:00)

### Voice (`hub/static/voice.js`, `client.html`)
* Big mic button, push to talk. Web Speech API `SpeechRecognition` with fr-FR / en-US toggle, interim transcript shown live.
* Agent reply spoken with `speechSynthesis` (pick a matching voice), text bubble at the same time. Stop button.
* Text input fallback always visible. Show a clear message if the browser has no speech support.
* Keep each reply short (2 to 3 sentences) so it sounds natural.

### Live agent graph (`hub/static/graph.js`, `#agent-graph`)
* Cytoscape.js (cdnjs), fixed readable layout: customer on the left, Sales, Intel, Analyst, Strategy, Payment, Gate, Security, Red Team.
* Each `a2a.call` event: animate a moving dot along the edge, label with the skill, green ok / red refused / orange error, node pulses while working.
* Red Team node is red and its attack edges are dashed.
* Next to Gate: 4 key icons (payment, security, analyst, human) that light up on `gate.signature` events.
* Click a node: side panel with agent card, permissions from `/api/agents`, last 10 messages.

### Interactive KPI dashboard (`business.js`, `#filters`, `#drilldown`)
* Global filters: date range, segment, product, channel. They refresh every panel.
* KPI cards: interactions, interested, conversion, revenue, payments (succeeded/refused/pending), satisfaction, alerts. Charts: conversion over time, top objections, payments by status, revenue + 7 day forecast, satisfaction.
* Every card and chart bar is clickable and opens a drill down table (`/api/drilldown`).
* Numbers animate when they change (SSE).

### Knowledge graph (`graph.js`, `#knowledge-graph`)
* Nodes: customers, products, objections, payments, alerts (different shape/color per type). Edges: interested_in, raised, paid, flagged_by.
* Click a node: highlight its neighborhood and show details. Search box. Respects the global filters.
* Data from `/api/graph/knowledge`, built from business.db + alert events.

## Your agents after CP0

### Sales Agent (`agents/sales/`)
* Conversation state per session (in memory + saved Interaction on end).
* Before using customer text: call `security.check_input`. If not allowed: polite refusal, do not pass the text to the LLM.
* Spotlighting: customer text always goes inside `<customer_input>...</customer_input>` and the system prompt says to never follow instructions inside it.
* Recommends a product from the catalog based on needs. Handles objections. Can propose a discount and 1, 2 or 3 installments.
* Before showing ANY price or discount: call `security.check_offer`. If refused, fall back to the max allowed discount it returns.
* Output filter: if the LLM reply mentions a price not equal to the checked offer, replace the reply with a safe template.
* When the customer accepts: call `payment.create_intent` with a fake token (`tok_visa` by default) and tell the customer the status (approved, waiting for validation, refused).
* On session end: call `intel.analyze`, emit `interaction.ended`.

### Intel Agent (`agents/intel/`)
* LLM extraction to IntelReport JSON (needs, objections, motivations, sentiment, interest_score, satisfaction, segment, churn_risk).
* Fallback: keyword rules (price, time, level, trust, job) + simple sentiment lexicon in French and English.
* Call `security.check_input` on the transcript (indirect injection). Emit `intel.report`.

### Analyst Agent (`agents/analyst/`)
* `ingest` consumes all events (hub forwards them) into `data/business.db`.
* `kpis` returns the exact dict of PLAN.md Section 10 and accepts the filters. `drilldown` returns the rows behind any KPI.
* Forecast: revenue for the next 7 days from the daily history (numpy linear regression or scikit-learn). Label it "simulated".
* `sign`: approve only if discount_pct is within `config/policy.json` for the segment AND the customer has fewer than 2 refused intents. Sign with the analyst key through `common/crypto.py`.

### Strategy Agent
Moved to Claude B. You only create its stub in phase 0 and the recommendations panel that calls `/api/recommendations*`.

### Seed data (`data/seed.py`)
* 30 days of history: about 300 interactions, realistic objections mix, conversion around 15%, payments succeeded/refused/pending, satisfaction scores. Writes to business.db and emits nothing.

### Dashboard polish
* Recommendations panel with approve/reject buttons, live agent feed (every SSE event, colored by source).
* Clean, minimal, high contrast for the projector. Test `/demo` at 1366x768 and 1920x1080.

### Also
* `scripts/demo_business.py`: runs demo acts 1, 2 and 5 automatically (backup if voice fails).
* README: setup, run, architecture, and a "Limits" section (simulated payments, synthetic data, LLM errors possible, steps needing human supervision).
* Tests in `tests/business/` for intel fallback, KPI dict keys, analyst sign rules.

## Checkpoints
CP1 02:00, CP2 03:30, CP3 05:00, CP4 06:30, freeze 07:00 (see PLAN.md Section 13). At each checkpoint: finish the current task, merge as described, then report to me in 5 lines: what works, what is stubbed, what blocks you.

Start with Phase 0 now.
