# Procura deterministic evaluation

Provider: `local`
Result: **15/15 (100.0%)**
Threshold: **90%**

| Scenario | Pass | Decision | Supplier |
|---|---:|---|---|
| happy_path | Yes | recommended | northstar |
| deadline_miss_visible | Yes | recommended | northstar |
| missing_authorization | Yes | review_required | — |
| expired_authorization | Yes | review_required | — |
| dosage_ambiguity | Yes | clarification | — |
| pack_mismatch | Yes | review_required | — |
| unsupported_destination | Yes | review_required | — |
| cold_chain | Yes | recommended | northstar |
| currency_mismatch | Yes | review_required | — |
| price_outlier | Yes | review_required | — |
| no_supplier | Yes | review_required | — |
| provider_failure | Yes | failed_safe | — |
| out_of_scope_follow_up | Yes | clarification | — |
| compact_strength_format | Yes | recommended | northstar |
| medicine_typo_confirmation | Yes | recommended | northstar |
