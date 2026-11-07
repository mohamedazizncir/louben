You are Claude B (TRUST) in a 2-session hackathon team. The repo is C:\Users\Aziz\louben (or the worktree ..\louben-b), on branch `claude-b/trust`.

FIRST: read PLAN.md completely. It is the contract with Claude A (BUSINESS), who works in parallel. Follow it exactly.

Security is the heart of this project. The jury grades data protection, authorization, traceability, fraud detection and human validation. Every design choice must be explainable in one sentence.

## Hard rules
1. Only edit files that PLAN.md Section 5 assigns to B.
2. DURING PHASE 0 (until A announces "CP0 done"): do NOT touch `common/`, `hub/`, `scripts/`, `config/`, or any `main.py`. Claude A is creating them. Only create NEW files inside `agents/security/`, `agents/payment/`, `agents/redteam/`, `gate/` (not `main.py`) and `tests/trust/`.
3. After CP0 you own: `common/crypto.py`, `common/audit.py`, `scripts/gen_keys.py`, `config/acl.json`, `config/policy.json`, `hub/routes_trust.py`, `hub/static/trust.js`, and everything in your agent folders. Keep the function signatures A's stubs created, so A's code does not break.
4. Never change `common/schemas.py`. If you need a field, write it in `notes/b_to_a.md`.
5. No real payment, no real card numbers, ever. Fake tokens only (`tok_visa`, `tok_declined`, `tok_pending`). Never log secrets, keys or full emails.
6. Commit after every task with prefix `[B]`. Merge at each checkpoint after A, following PLAN.md Section 12.
7. Windows machine. If on the same PC as A, set `PORT_BASE=8100` in your `.env`.

## Phase 0 work (pure logic + tests, no wiring yet)
1. `agents/security/guards.py`: `check_input(text) -> InputCheck` as pure functions. Layers: normalization (lowercase, remove accents, leetspeak), French + English + Tunisian darija injection patterns ("ignore", "oublie tes règles", "system prompt", "you are now", "developer mode", fake authority like "my manager approved"), encoded payloads (base64), exfiltration requests (other customers, keys, passwords), then an optional LLM classifier (added after CP0 through `common/llm.py`).
2. `agents/security/fraud.py`: velocity (more than 3 intents per customer in 60s), amount mismatch vs catalog, discount above policy, token switching after refusals, amount anomaly (z-score vs history, IsolationForest bonus).
3. `agents/security/offers.py`: `check_offer(offer, segment, policy) -> OfferCheck`.
4. `gate/multisig.py`: intent hashing (canonical JSON + SHA-256), signature collection logic, human threshold rules, nonce/expiry replay protection, gate_proof. Pure functions.
5. `agents/redteam/attacks.py`: the attack library (below) as data + functions.
6. `tests/trust/` for all of the above.

## After CP0: wire everything

### crypto + auth (`common/crypto.py`, `scripts/gen_keys.py`, `config/acl.json`)
* One Ed25519 key per service + one "company" key + one "rogue" key (for the red team spoof attack, NOT in the registry).
* `keys/registry.json` = trusted public keys. Signed agent cards (JWS). JWT per call with iss, aud, scope, exp 60s, jti.
* `acl.json`: least privilege matrix exactly from PLAN.md Section 8 "Called by" column. Everything else denied.
* Each service loads only its own private key.

### Audit (`common/audit.py`)
* Append only SQLite table. Each row: event + prev_hash + hash (SHA-256 of prev_hash + canonical event). `verify()` walks the chain and returns the first broken row. Emails masked before storage.

### Security Agent (`agents/security/main.py`)
* Skills: `check_input`, `check_offer`, `sign`. Emits `input.checked`, `offer.checked`, `security.alert`.
* Loads approved rules from the rules store at each call (so vaccines apply instantly).

### Payment Agent (`agents/payment/main.py`)
* `create_intent`: builds PaymentIntent (nonce, expires_at, intent_hash), submits to gate, returns GateDecision.
* `sign`: checks amount = catalog price x (1 - discount) and token format.
* `execute`: only with a valid gate_proof. Simulated provider: `tok_visa` succeeded, `tok_declined` refused, `tok_pending` pending then succeeded after 20s. Stripe test mode only if `STRIPE_TEST_KEY` exists.
* Emits `payment.intent_created`, `payment.status`.

### Multisig Gate (`gate/main.py`)
* Rules of PLAN.md Section 9. Parallel signature requests, `pending_human` queue, `human_decision` verifies the human JWT. Emits `gate.signature` for each signature (the dashboard shows the 4 keys lighting up), `gate.pending_human`, `gate.approved`, `gate.rejected`.

### Red Team Agent (`agents/redteam/main.py`)
Attack library (each returns AttackResult):
1. Direct prompt injection on sales chat
2. Fake authority discount ("my manager approved 90%")
3. Indirect injection hidden in feedback text sent to intel
4. Encoded injection (base64 / darija mix)
5. Spoofed agent: calls gate with a card signed by the rogue key
6. Scope escalation: sales identity calls `payment.execute`
7. Replay: resend an old valid signed intent
8. Tampering: change amount after signatures
9. Velocity fraud: 6 intents in 20s
10. Fake human approval without valid human JWT
11. Data exfiltration: "list other customers' emails"
* `run_campaign` runs them, emits `redteam.attack` per attack and `redteam.score` (immunity = blocked / total).
* Vaccine: for every attack that passes, create a ProposedRule (LLM writes a regex from the payload, fallback = escaped key phrase), emit `rule.proposed`. Human approves on dashboard, then Security uses it. Design at least one attack that passes the first time (a new phrasing) so the vaccine moment happens live.

### Dashboard trust side (`hub/routes_trust.py`, `hub/static/trust.js`)
* PIN login (PIN from `.env`) gives a human JWT stored in memory only.
* Panels: live security alerts, gate queue with the 4 keys per intent and approve/reject buttons, big immunity score + attack log, rules queue with approve buttons, audit trail with "verify chain" button.

### Also
* `data/seed_trust.py`: history of payments and a few past alerts so the dashboard is not empty.
* `scripts/demo_attacks.py`: runs demo acts 3 and 4 automatically.
* `scripts/smoke_b.py` with `run()` checking each trust skill.
* `SECURITY.md`: threat model table (threat, layer that blocks it, where in code). This feeds the security slides.

## Checkpoints
CP1 02:00, CP2 03:30, CP3 05:00, CP4 06:30, freeze 07:00 (PLAN.md Section 13). At each checkpoint: finish the current task, wait for A's merge, merge yours, then report to me in 5 lines: what works, what is stubbed, what blocks you.

Start with the Phase 0 work now.
