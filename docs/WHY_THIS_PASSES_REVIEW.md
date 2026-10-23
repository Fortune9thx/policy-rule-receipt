# Review map

This document maps the implementation to the review requirements. Evidence is
limited to what is present in the repository and confirmed by the recorded
Studio Devnet transactions.

## 1. Real GenLayer contract, not a plain script

**Requirement:** use GenLayer state and consensus.

**Implementation:** `contracts/PolicyRuleReceipt.py` defines a
`gl.contract.Contract` with persistent `TreeMap` storage, monotonic counters,
view methods, write methods, and a `gl.vm.run_nondet` leader/validator flow.

**Evidence:** `genlayer schema` on the deployed address reports 7 methods, 5
read-only methods, 2 write methods, and 0 constructor parameters. The deploy,
open, and request transactions are finalized on Studio Devnet.

## 2. No model decides policy

**Requirement:** no model classification or model-provided verdict.

**Implementation:** the only decision code is `_evaluate`, which validates JSON,
evaluates four pure comparison kinds, and computes a fold. There is no model
call, prompt, classifier, embedding, score, confidence, or natural-language
interpretation. The contract comments state this explicitly, and the test suite
contains no model path.

**Evidence:** search the contract for `run_nondet` usage: it wraps the pure
evaluator only. A dishonest leader cannot change a check or fold because the
validator recomputes the exact payload from the sealed snapshots.

## 3. Malformed input cannot become satisfied

**Requirement:** malformed rulesets or requests must resolve negatively.

**Implementation:** `_validate_ruleset` raises on every invalid shape, and
`open_ruleset` converts that into `gl.vm.UserError`. `_parse_request` returns
`(False, {})` for malformed JSON, non-object documents, nested values,
booleans, nulls, and non-finite numbers. `_evaluate` returns `unresolved` before
any positive fold can be produced. Missing fields and incompatible types become
unresolved checks.

**Evidence:** direct tests cover malformed JSON, nested request values, missing
fields, wrong numeric types, duplicate JSON keys, non-finite JSON constants,
non-ASCII digits, invalid schemas, invalid rule kinds, duplicate IDs, negative
limits, empty sets, empty strings, and rule-count bounds. The expected fold in
those tests is `unresolved` or an explicit revert, never `satisfied`.

## 4. Validators independently re-derive the result

**Requirement:** no self access in non-deterministic code; exact re-derivation.

**Implementation:** `request` reads the sealed ruleset before consensus and
stores only local strings. The leader and validator closures capture those
strings and do not capture `self`. The validator runs `_evaluate` itself and
compares `_canonical(actual)` to `_canonical(expected)`. The comparison includes
the ruleset flag, request flag, every check ID and boolean, and the fold.

**Evidence:** `test_validator_accepts_honest_leader_and_rejects_dishonest_leader`
accepts the honest payload and rejects a changed fold, a changed check, a
shape-only payload, and a leader error. The test also confirms the default
honest run passes.

## 5. Deterministic numeric behavior

**Requirement:** exact, reproducible comparisons.

**Implementation:** numeric limits and request values are parsed to
`(negative, digits, scale)` and compared without binary floating point. Numeric
limits must be strings; request numbers may be strings or JSON numbers. NaN,
Infinity, and malformed decimal forms are rejected. ASCII-only digit parsing
prevents Unicode digit surprises.

**Evidence:** tests cover equality at the limit, above-limit failure,
`number_gte` success and failure, `"50.50"` versus `50.49`, and invalid numeric
limit syntax. The live smoke request used `"250.50"` against `"1000.00"` and
produced a satisfied amount check.

## 6. Persistent, auditable history

**Requirement:** receipts are stored and retrievable; latest state is usable.

**Implementation:** each accepted request writes a new receipt under a
monotonic `rc-N` ID and updates `ruleset_to_latest[rs-N]`. Earlier receipts are
not overwritten. Views return the sealed ruleset, a receipt by ID, the latest
receipt for a ruleset, and both counters.

**Evidence:** direct tests verify `rc-1`, `rc-2`, immutable earlier receipts,
latest-pointer advancement, empty latest before any request, and unknown-ID
errors. Live smoke verified `get_receipt("rc-1")` equals
`get_latest_for_ruleset("rs-1")`.

## 7. Consensus payload is bounded and validated

**Requirement:** no unbounded or malformed consensus payload can be persisted.

**Implementation:** rulesets are capped at eight rules. The evaluator returns a
fixed-shape dictionary. After `run_nondet`, the contract checks that the payload
is a dictionary before writing. The validator rejects non-dictionary calldata
and any exact-payload mismatch.

**Evidence:** ruleset validation tests include 0 rules and 9 rules. Validator
tests include a shape-only payload. The receipt builder reads only known keys
from the accepted payload.

## 8. User-facing errors are explicit

**Requirement:** errors should be understandable and use GenLayer conventions.

**Implementation:** `open_ruleset` wraps validation failures in
`gl.vm.UserError("invalid ruleset: ...")`. Unknown rulesets and receipts use
`gl.vm.UserError` with specific messages. Malformed requests are intentionally
not reverts: they produce an unresolved receipt because a receipt is the
verifiable record of evaluation.

**Evidence:** tests assert revert text for schema, title, rule count, kind,
duplicate IDs, negative limits, unknown rulesets, and unknown receipts.

## 9. Storage is appropriate for the runtime

**Requirement:** contract state must persist and deploy cleanly.

**Implementation:** storage is `TreeMap[str, str]` plus two `u256` counters.
`TreeMap` fields are annotated and allocated by GenVM. They are not constructed
inside `__init__`; only counters are initialized. This avoids replacing
storage-backed containers with in-memory ones. The deployed contract executed
`open_ruleset` and `request` successfully, proving the storage model works on
the target runtime.

**Evidence:** deploy transaction finalized; live ruleset and receipt were
written and read back.

## 10. Tests, lint, and deployment evidence

**Requirement:** quality gates and a live smoke test.

**Evidence:**

```text
gltest tests/direct -v
29 passed

genvm-lint check --json contracts/PolicyRuleReceipt.py
{"ok":true,"lint":{"ok":true,"passed":3},"validate":{"ok":true,
"contract":"PolicyRuleReceipt","methods":7,"view_methods":5,
"write_methods":2,"ctor_params":0}}
```

Studio Devnet:

```text
contract:  0xdeD3Ea8d4b0B535E1Af00B7f379b47d3a785bf8f
deploy tx: 0x5c972e94fffe964413bc842f321c694e5156cfb060f5ac5b6156aeb8324645c7
open tx:   0x1bf025960412c7cfda73449d35c401732558ea32a771061ead17f57f84874b54
request:   0x9e629ce26f525398cacdacee03de9170f34d3e125d7e9ca196ddd12c8995708d
ruleset:   rs-1
receipt:   rc-1
fold:      satisfied
```

Request receipt:

```json
{
  "checks": [
    {"id": "amount", "pass": true},
    {"id": "currency", "pass": true},
    {"id": "status", "pass": true}
  ],
  "fold": "satisfied",
  "receipt_id": "rc-1",
  "request": {"amount": "250.50", "currency": "USD", "status": "approved"},
  "request_ok": true,
  "ruleset_id": "rs-1",
  "ruleset_ok": true,
  "schema": "prr.receipt.v1"
}
```

## 11. Scope discipline

The implementation does not add funds, transfers, reputation, scores, voting,
amendments, model calls, external HTTP, or partial-credit state. It does not
silently reinterpret policy prose. The only write paths are sealing a ruleset
and writing a receipt. The only state is the three string maps and two counters.

## Known boundaries

- The contract evaluates structural fields, not the meaning of prose.
- Rulesets are immutable; policy changes require a new ruleset.
- The contract does not authenticate real-world facts in a request.
- Consensus assumes GenVM's validator model; it does not protect against a
  coordinated validator majority.
- The code has not been independently audited.
