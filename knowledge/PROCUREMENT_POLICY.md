# Procura procurement review policy

**Version: procura-policy-v1**

These are illustrative operating rules, not legal or regulatory advice and not any company's methodology.

- The model must never invent supplier, product, authorization, price, inventory, or conversion-rate facts. Only repository data and deterministic tool results establish supplier facts.
- The model may interpret intent and explain results. Arithmetic, eligibility, deadlines, currencies, and ranking are deterministic.
- Missing or ambiguous medicine, strength, dosage form, quantity, pack size, or units requires clarification or human review.
- Missing or expired authorization, unsupported destination, cold-chain incompatibility, pack mismatch, or currency mismatch without a verified rate requires human review.
- No eligible supplier, conflicting data, price anomaly, tool failure, or invalid model output after one retry requires human review.
- A recommendation is not a transaction. Procura cannot place orders, contact suppliers, or approve compliance.
- Human actions are recorded with reviewer action and timestamp.

## Ranking

Eligibility is a hard gate. Among eligible quotes: `score = 0.50 × price_score + 0.25 × delivery_score + 0.25 × reliability`, where price and delivery scores are min/value on a 0–1 scale. A quote more than 2.5× the median total is a price anomaly and is escalated. No currency conversion is fabricated.
