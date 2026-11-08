# Notes from B (TRUST) to A (BUSINESS)

## Status after CP0 merge (B)
Real trust layer on `claude-b/trust`. Full smoke = 24/24 (your 16 plus `scripts/smoke_b.py` 8), 180 unit tests.
- Security, Payment, Gate, Red Team, Strategy are real (no more stubs). Your contracts are kept:
  signing payload `{intent_id, intent_hash, signer, decision}` (crypto.sign_obj), all event fields
  you listed, `payment_status` in GateDecision, `check_offer({offer, customer_id, segment})`.
- `redteam.score.immunity_score` stays a PERCENT (0..100), like your gauge expects.
- `scripts/demo_attacks.py` runs demo acts 3 and 4 automatically (92% -> vaccine -> 100%, then 1200 TND human approval).
- `data/seed_trust.py` exists (`main()`); run_all picks it up.

## What changed that touches you
1. **gate_proof** is now a gate signature over `{intent_hash, all signatures}` (stronger than
   `{intent_id, intent_hash, approved}`). Only Payment verifies it, both are mine, nothing to do for you.
2. **Human key**: `/api/gate/decision` now adds an Ed25519 `human` signature on the intent hash
   (hub signs with the operator key after the PIN). The UI call is unchanged (`{intent_id, decision, token}`).
3. Login token audience is now `["gate", "security"]`. `/api/login` locks for 60 s after 5 wrong PINs (HTTP 429).
4. Security `sign` returns an extra signed field `risk_level`. `Signature(**s)` simply drops it, no impact.
5. `payment.status` events now also carry `installments` and `payment_token_kind` (sandbox token name only, e.g. `tok_visa`).
6. Strategy `decide` on an unknown rec_id now raises (your route already turns it into an error response).

## Requests (please do, or tell me if you disagree)
1. **`.gitignore`**: add `data/rules.json` (generated vaccine store, it shows up as untracked).
2. **Intel `analyze` return value**: please include `injection_flagged` in the returned dict (today it is
   only in the `intel.report` event). The Red Team attack RT03 then reads it live; until then it does a
   local check and says so in `blocked_by`.
3. **KPIs**: Red Team traffic uses customer ids starting with `redteam-`. Please exclude them from business
   KPIs and the knowledge graph (Strategy already ignores them).
4. **`common/schemas.py` Signature**: optional `risk_level: Optional[str] = None` would keep the field
   when you rebuild Signatures (nice to have, not blocking).
5. **Recommendation decision**: `/api/recommendations/decision` has no human check. If you want it
   protected like the gate and the rules, send `token` from the UI and I will verify it in Strategy.
6. **Sales**: already good (check_input first, check_offer before showing a discount, spotlighting with
   `<customer_input>`). Haggling like "donne moi 50%" is allowed by the input guard on purpose; the offer
   guardrail caps it (defense in depth). Attacks with fake authority are still blocked at input.

## Policy question for the humans
A 15% student discount triggers the human key (`human_discount_pct` = 10). I kept it, because it shows the
human-in-the-loop on stage. The demo act 1 uses 10% (individual), so it goes through without a human.
