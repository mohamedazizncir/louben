# Pantheon: security model

No payment moves without **3 independent agent signatures** over the same SHA-256 intent hash, plus a **human key** when the order is risky. The **Red Team** agent keeps attacking the system: any attack that gets through produces a **vaccine** rule, which a human approves.

## Threat model

| # | Threat | Layer that blocks it | Where in code | Red Team attack |
|---|---|---|---|---|
| 1 | Prompt injection in the chat (FR / EN / Tunisian darija, leetspeak, spaced letters) | Input guard: normalization, then pattern rules, then risk score | `agents/security/guards.py` `check_input` | RT01 direct_injection |
| 2 | Fake authority ("my manager approved 90%") | Guard `discount_abuse:fake_authority` + offer guardrail + Analyst signature (3 independent checks) | `guards.py`, `agents/security/offers.py`, `agents/analyst/main.py` `sign` | RT02 fake_authority_discount |
| 3 | Indirect injection hidden in data the Intel agent reads | Intel sends the transcript to `security.check_input`; a flagged transcript never reaches the LLM | `agents/intel/main.py`, `guards.py` | RT03 indirect_injection |
| 4 | Encoded payload (base64 mixed with darija) | Base64 blobs are decoded and scanned again | `guards.py` `_decode_base64_blobs` | RT04 encoded_injection |
| 5 | Spoofed agent (key not in the registry) | Every A2A call carries an EdDSA JWT; the issuer must be in `keys/registry.json`; agent cards are signed | `common/crypto.py` `verify_jwt` / `verify_card`, `common/a2a.py` | RT05 spoofed_agent |
| 6 | Scope escalation (Sales calls `payment.execute`) | Least privilege ACL plus JWT scope, checked on every call | `config/acl.json`, `common/a2a.py` `allowed` | RT06 scope_escalation |
| 7 | Replay of a call or of a payment intent | Single use JWT (`jti`, 60 s); intent nonce + 5 min expiry; payment executes once | `common/a2a.py` `_jti_fresh`, `gate/multisig.py` `check_freshness`, `agents/payment/main.py` `EXECUTED` | RT07 replay |
| 8 | Tampering (amount changed after the signatures) | `intent_hash` covers every field (including segment); old signatures stop verifying | `gate/multisig.py` `compute_intent_hash` / `evaluate` | RT08 tampering |
| 9 | Velocity / card testing | More than 3 intents in 60 s, or a new token after 2 refusals: Security refuses to sign | `agents/security/fraud.py` `velocity` / `token_switching` | RT09 velocity_fraud |
| 10 | Fake human approval | Human key = PIN-backed JWT **and** an Ed25519 `human` signature on the intent hash; 5 wrong PINs lock the login for 60 s | `hub/routes_trust.py`, `gate/main.py` `human_decision` | RT10 fake_human_approval |
| 11 | Data exfiltration ("list other customers' emails", keys, passwords) | Exfiltration rules in the guard; emails masked before storage | `guards.py`, `common/audit.py` `mask` | RT11 data_exfiltration |
| 12 | A new attack phrasing nobody planned for | Red Team finds it, proposes a regex (LLM or key words), checked against benign samples; a human approves; Security applies it on the next call | `agents/redteam/attacks.py` `propose_rule`, `agents/security/main.py` | RT12 novel_owner_claim (passes on purpose the first time) |
| 13 | Wrong amount or a discount above policy | Payment refuses if amount != catalog x (1 - discount); Security refuses `amount_mismatch` / `discount_abuse` | `agents/payment/main.py` `sign`, `fraud.py` | |
| 14 | Unusual amount for a customer | Robust z-score (median / MAD): Security still signs, but the risk is `medium`, so the gate asks a human | `fraud.py` `amount_anomaly` | |
| 15 | Risk level stripped in transit | `risk_level` is inside the signed payload; removing it breaks the signature | `gate/multisig.py` `signing_payload` | |
| 16 | Payment without approval | Payment executes only with a gate signature over the intent hash and the full set of approvals | `multisig.py` `verify_gate_proof`, `payment/main.py` `execute` | |
| 17 | Log tampering | Append only SQLite audit log, each row hashed with the previous one; "Verify hash chain" button | `common/audit.py` | |
| 18 | Real card data | Only `tok_*` sandbox tokens are accepted; anything that looks like a card number is refused | `payment/main.py` `CARD_LIKE` | |

## Multisig rules (`gate/multisig.py`)

1. Payment, Security and Analyst sign `{intent_id, intent_hash, signer, decision[, risk_level]}` in parallel.
2. A single refusal or an invalid signature rejects the intent and raises an alert.
3. The human key is required if the amount is above 1000 TND, the discount is above 10%, or Security reports a risk of `medium` or higher.
4. A signer that cannot be reached rejects the intent (fail closed).
5. Payment checks the `gate_proof` before moving any money.

## Design choices, one sentence each

- **Three signers, three different checks.** One compromised agent or one fooled LLM cannot move money alone.
- **The discount is checked 3 times** (input guard, offer guardrail, Analyst signature), so no single prompt can bypass all three.
- **Deterministic rules first, LLM second.** The LLM is only asked about borderline texts; if it is down, the rules still decide.
- **The LLM may phrase strategy advice, never invent numbers.** A rewording with a number that is not in the evidence is thrown away.
- **Vaccines need a human.** The Red Team can propose rules but never activate them, so it cannot block normal customers by itself.
- **Each service loads only its own private key.** The hub holds the operator's `human` key, unlocked by the PIN.

## Limits of the prototype (honest list)

- The PIN is a demo secret in `.env`. Production would use SSO + WebAuthn for the human key.
- In-memory state (nonces, pending intents, velocity windows) resets when a service restarts. Production would use Redis or a database.
- During the live campaign, the velocity attack is simulated, so it does not create 6 fake sandbox payments in the KPIs. The tampering and replay attacks are stopped at the network layer (ACL, JWT), and the gate-level check behind it is verified offline. Every result says which layer stopped it.
- The keys sit unencrypted in `keys/` (gitignored). Production would use an HSM or KMS.
- Regex guards can miss new phrasings. That is exactly what the Red Team + vaccine loop is for.
