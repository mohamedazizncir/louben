# Notes from A (BUSINESS) to B (TRUST)

## CP0 delivered (00:40)
Everything runs end to end: `python scripts/run_all.py --seed` then `python scripts/smoke_test.py` = 16/16.
Your files now belong to you. They are WORKING stubs, not empty ones: improve them, don't break the contracts.

### Your files (written by A in phase 0)
common/crypto.py, common/audit.py, scripts/gen_keys.py, config/acl.json, config/policy.json,
agents/{payment,security,redteam,strategy}/main.py, gate/main.py, hub/routes_trust.py, hub/static/trust.js

### Contracts the UI and my agents rely on (please keep)
* Signature payload signed by each signer: `{intent_id, intent_hash, signer, decision}` (crypto.sign_obj).
* gate_proof = gate signature over `{intent_id, intent_hash, approved: true}`.
* `payment.status` event data must include: intent_id, status, amount, customer_id, product_id, segment (analyst KPIs).
* `gate.signature` data: {intent_id, signer, decision, reason} → lights the 4 keys on the graph.
* `gate.pending_human` data: {intent_id, customer_id, amount, product_id, reason}. `gate.approved`: {intent_id, amount, payment_status}.
* `gate.rejected` data: {intent_id, customer_id, amount, product_id, reasons[]}.
* `security.alert` data: {type, severity, customer_id?, target?, details{}}.
* `redteam.attack` = AttackResult, `redteam.score` = {immunity_score, blocked, total}.
* `rule.proposed` / `rule.approved` = ProposedRule. `strategy.recommendation` = {items: [Recommendation]}.
* GateDecision returned to Sales includes `payment_status` (optional field I added).
* Sales calls `security.check_offer` with `{offer, customer_id, segment}` and expects OfferCheck with `max_discount_pct`.
* trust.js mounts on ids: immunity-score, redteam-log, security-alerts, gate-queue, rules-queue, audit-trail. It uses `Bus.on()` and `UI.*` from bus.js.

### Ideas / known gaps for you
1. `security.check_input`: the leetspeak normalization turns digits into letters, so "50%" becomes "so%" and the discount regex misses it. (The offer guardrail still caps it, good for the "defense in depth" story, but fix if you want the input guard to catch it.)
2. `encoded_injection` is designed to PASS the first time → vaccine proposed → human approves → 100%. Keep at least one such attack for the live "vaccine" moment. Note: `run_all --seed` deletes data/rules.json and data/audit.db for a clean demo.
3. Policy: a 15% student discount triggers the human key (human_discount_pct = 10). Decide if that's what we want on stage.
4. Missing attacks: tampering (amount changed after signatures), velocity (6 intents in 20s), indirect injection through intel.
5. `data/seed_trust.py` is picked up automatically by run_all if you create it (function `main()`).
6. Strategy stub recommendations are basic. Make them sharper (they're in the final pitch).
