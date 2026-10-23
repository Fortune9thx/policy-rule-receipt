# Security

## Scope

This document covers the `PolicyRuleReceipt` contract in
`contracts/PolicyRuleReceipt.py` and its direct-mode test suite. It does not
claim an independent audit, formal verification, or a guarantee about the truth
of off-chain data submitted in a request.

## Assets and trust boundaries

The contract holds no funds and makes no external calls. Its important assets
are:

- the integrity of sealed rulesets;
- the integrity of receipt history;
- the correctness of the leader/validator decision;
- the ability of any caller to read the exact policy and receipt data.

Trust boundaries:

1. **GenVM runtime and validator set.** The contract relies on GenVM's
   non-deterministic execution and validator consensus.
2. **Callers.** Anyone may seal a ruleset or submit a request. All inputs are
   untrusted.
3. **Off-chain observers.** They can recompute a receipt from the sealed
   ruleset and request, but they must obtain those values from the chain or a
   trusted source.
4. **Deployment tooling.** Deployment and post-deployment scripts are outside
   the contract's trust boundary once the transaction is finalized.

## Security properties

### P1: A malformed ruleset cannot be sealed

`_validate_ruleset` checks the schema, title, rule count, rule shape, unique
IDs, supported kinds, field names, numeric limit syntax, allowed sets, expected
strings, and all length caps. Any exception is converted by `open_ruleset` into
`gl.vm.UserError`. No counter or storage entry is written on failure.

### P2: A malformed request cannot be satisfied

`_parse_request` rejects malformed JSON, non-object documents, duplicate keys,
non-finite JSON constants, booleans, nulls, arrays, nested objects, and
non-finite numeric values. `_evaluate` returns `unresolved` before accepting a
positive fold. Missing fields and incompatible values are also `unresolved`.

### P3: A failed check cannot be reported as satisfied

The fold is computed after all checks. `satisfied` requires every check to be
true and no unresolved condition. A validator recomputes the entire payload and
rejects any exact mismatch.

### P4: Validators do not access contract storage during consensus

The sealed ruleset and request are copied to local strings before
`gl.vm.run_nondet`. The leader and validator closures do not capture `self`.
They call the pure evaluator. This avoids storage reads or writes inside
non-deterministic execution.

### P5: Receipt history is append-only by construction

Each accepted request increments `receipt_counter` and writes a new key
`rc-N`. Existing receipt keys are never overwritten. The latest pointer is a
separate mapping and does not remove older receipts. There is no delete,
amend, or update method.

### P6: Inputs are bounded

Rulesets are limited to eight rules. Titles, IDs, field names, allowed values,
and expected strings have explicit length caps. This bounds the work and the
size of the consensus payload.

### P7: Numeric decisions are exact and deterministic

Numeric rules use decimal `(negative, digits, scale)` values rather than binary
floating point. The parser rejects non-finite values and malformed syntax.
ASCII-only digit checks avoid Unicode digit ambiguity.

### P8: Unknown IDs fail closed

Unknown rulesets and receipts raise `gl.vm.UserError`. The latest view returns
`""` only when the ruleset exists but has no receipt yet.

## Threat analysis

### Dishonest leader

A leader can return a payload that changes a fold, a check, an ID, or the
ruleset/request validity flags. The validator recomputes the expected payload
from the same snapshots and compares canonical JSON exactly. Any difference is
rejected. A leader error is also rejected.

### Dishonest validator

A validator that returns `False` for an honest payload causes disagreement
rather than acceptance. The contract does not implement a custom voting scheme;
it uses GenVM's `run_nondet` semantics and the configured validator set.

### Malicious ruleset author

A ruleset author can choose any supported structural policy. The contract does
not judge whether that policy is sensible, fair, or legally sufficient. Once
sealed, the policy cannot be changed. Consumers should read the sealed ruleset
before relying on a receipt.

### Malicious requester

A requester can submit arbitrary JSON and can repeat requests. The contract
sanitizes input, bounds evaluation, and writes a receipt for each accepted
request. It does not rate-limit or charge for requests; that is a deployment
concern.

### Storage corruption or manual mutation

`_evaluate` re-validates the sealed ruleset on every request. A corrupted
ruleset produces `unresolved`. The contract does not provide a migration or
repair function. A new deployment would be required for a corrupted store.

### Replay and ID confusion

Ruleset and receipt IDs are namespaced (`rs-` and `rc-`) and monotonic. A
receipt stores its own ID and the ruleset ID it evaluated. Consumers should
check both fields rather than trusting a caller-supplied association.

### Duplicate JSON keys

Duplicate keys in a ruleset or request are rejected. This avoids ambiguity
between parsers and prevents a sealed policy from being interpreted differently
than its visible text suggests.

### Numeric edge cases

The parser rejects NaN, Infinity, and malformed exponents. It accepts ordinary
decimal strings and finite JSON numbers. A JSON number that is too large to be
represented as a finite float is rejected by request parsing; use a decimal
string for large exact values.

### Denial of service

Rules are limited to eight, values are length-capped, and evaluation is linear
in the number of rules. There is no unbounded loop over caller-controlled
collections beyond the capped rule list and allowed set. `set_contains` scans
the allowed list, which is not explicitly length-capped by count but each item
is capped at 64 characters and the overall JSON is bounded by transaction
limits. Deployers should still enforce practical request-size limits at the
gateway if needed.

## Privacy

All rulesets, requests, receipts, and transaction data are public on-chain.
Never submit secrets, credentials, personal data, or confidential business
information. Hash sensitive identifiers off-chain if only equality is needed,
and understand that equality checks can still leak information.

## Operational recommendations

- Read the sealed ruleset before trusting a receipt.
- Verify that `receipt.ruleset_id` matches the ruleset you intend to evaluate.
- Treat `unresolved` as "not approved" for any workflow that requires a
  positive decision.
- Monitor for unexpected rulesets and receipts if the contract is public.
- Keep deployment keys in a secure keystore; never commit keystores or
  passwords.
- Do not treat a testnet deployment as production financial infrastructure.
- Obtain an independent review before using the contract in a high-value
  setting.

## Reporting

If you find a vulnerability, open a private security advisory on the GitHub
repository or contact the repository owner through GitHub. Include the affected
method, a minimal reproduction, and the expected versus actual behavior. Do not
disclose a working exploit publicly before it can be assessed.

## No warranty

The software is provided under the MIT License, without warranty. It has not
been independently audited.
