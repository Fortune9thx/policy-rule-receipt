# Changelog

All notable changes to this project are documented here.

## [1.0.0] - 2026-10-23

### Added

- `PolicyRuleReceipt` contract with sealed rulesets, deterministic evaluation,
  leader/validator consensus, and append-only receipts.
- Four check kinds: `number_lte`, `number_gte`, `set_contains`, and `string_eq`.
- Strict JSON parsing with duplicate-key and non-finite-number rejection.
- Exact decimal comparison without binary floating point.
- Bounded rulesets (1 to 8 rules) and explicit string length limits.
- Public views for rulesets, receipts, latest receipt per ruleset, and counters.
- 29 direct-mode tests covering validation, folds, malformed input, consensus
  tampering, history, and unknown IDs.
- Studio Devnet deployment and a finalized live smoke test.
- Design, review map, security model, and portal submission documentation.
- Linux CI workflow for lint and direct-mode tests.

### Deployment

- Contract: `0xdeD3Ea8d4b0B535E1Af00B7f379b47d3a785bf8f`
- Network: Studio Devnet (`61997`)
