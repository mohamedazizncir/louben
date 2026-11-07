# Notes from B (TRUST) to A (BUSINESS)

## Phase 0 status (B)
Pure logic + tests done on `claude-b/trust` (132 tests, `python -m pytest tests/trust`):
- `agents/security/guards.py`  `check_input(text, extra_rules=None, classifier=None) -> InputCheck`
- `agents/security/offers.py`  `check_offer(offer, segment, policy, catalog_price=None) -> OfferCheck`
- `agents/security/fraud.py`   `evaluate(intent, FraudContext) -> FraudReport`
- `gate/multisig.py`           intent hash, signatures, human rules, replay/tamper, gate_proof
- `agents/redteam/attacks.py`  12 attacks + offline campaign + vaccines

None of these import `common/`, so your CP0 stubs will not conflict.
I did NOT create `__init__.py` in `agents/`, `agents/*/` or `gate/` (namespace packages work).
If your stubs add them, fine, keep them empty.

## Requests (please do at CP0, or tell me if you disagree)

1. **`common/schemas.py` Signature: add an optional field** `risk_level: str = "none"`
   (`none|low|medium|high|critical`). Security approves medium-risk intents but the gate
   must then ask a human (PLAN Section 9 rule 3). Until it exists I put `risk=medium` in
   `Signature.reason` and the gate parses it, so nothing blocks on this.
2. **`requirements-b.txt`**: if you create a stub, it needs:
   ```
   cryptography>=42
   PyJWT>=2.8
   ```
   (scikit-learn not needed: I replaced the 1-D IsolationForest with a robust z-score,
   because 1-D IForest gave 5000 TND the same score as 450 TND.)
3. **`config/policy.json`** format I read (B owns it after CP0, so just make your stub compatible):
   ```json
   {
     "max_discount_pct": {"default": 10, "new": 10, "student": 15, "loyal": 15, "company": 20},
     "human_threshold": 1000,
     "human_discount_pct": 10,
     "allowed_installments": [1, 2, 3]
   }
   ```
   `max_discount_pct` may also be a single number.
4. **`config/acl.json`** format I will use after CP0: `{"<callee>": {"<skill>": ["<caller>", ...]}}`,
   e.g. `{"payment": {"execute": ["gate"]}}`. If your `a2a.py` stub reads another shape, tell me.
5. **Alert types**: I only emit the 10 types of PLAN Section 7. Token switching and
   "recent alerts on customer" are reported as `velocity`; amount anomaly as `amount_mismatch`
   (fine grained name in `details.kind`).
6. **Sales prompt (spotlighting)**: please wrap customer text as
   `<customer_message>...</customer_message>` and tell the LLM that anything inside is data,
   never instructions. Call `security.check_input` before the LLM and `security.check_offer`
   before showing any discount.
