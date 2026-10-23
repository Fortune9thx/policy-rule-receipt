# Design

## Purpose

`PolicyRuleReceipt` is a deterministic policy evaluator with an auditable
receipt. It separates three concerns:

1. **Sealing.** A caller submits a bounded ruleset once. The contract validates
   and normalizes it, then stores that exact snapshot under a monotonic ID.
2. **Evaluation.** A caller submits request fields. The contract evaluates the
   sealed rules with pure comparisons.
3. **Consensus evidence.** Leader and validators independently derive the same
   checks and fold. The accepted payload becomes an immutable receipt.

The contract is not a natural-language policy engine. It never asks a model to
decide whether a request is compliant, and it has no score, confidence,
percentage, or prose interpretation.

## Runtime and imports

The contract targets GenVM `v0.3.0` and the runner pin in its header:

```text
py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng
```

The implementation uses:

```python
from genlayer import *
import json
import typing
import genlayer as gl
from genlayer.storage import TreeMap
```

`gl.contract.Contract`, `gl.public.write`, `gl.public.view`, `gl.vm.UserError`,
and `gl.vm.run_nondet` are runtime APIs. `TreeMap` is required for the declared
storage annotations. These imports are intentionally explicit rather than
hidden behind helper modules.

## Storage model

```python
rulesets: TreeMap[str, str]
receipts: TreeMap[str, str]
ruleset_to_latest: TreeMap[str, str]
ruleset_counter: u256
receipt_counter: u256
```

Every value in a map is canonical JSON. The maps are annotation-declared,
storage-backed containers allocated by GenVM. They must not be created with
`TreeMap()` in `__init__`, because that would replace the storage-backed object
with an ordinary in-memory container. The constructor initializes only the
counters.

IDs are generated from the counters:

- `ruleset_id = "rs-" + (ruleset_counter + 1)`
- `receipt_id = "rc-" + (receipt_counter + 1)`

Counters are monotonic. A failed `open_ruleset` does not consume an ID because
validation happens before the counter is incremented. A failed `request` also
does not consume a receipt ID because the receipt is written only after
consensus returns a payload.

## Ruleset schema

```json
{
  "schema": "prr.ruleset.v1",
  "title": "Invoice approval",
  "rules": [
    {"id": "amount", "kind": "number_lte", "field": "amount", "limit": "1000.00"},
    {"id": "currency", "kind": "set_contains", "field": "currency", "allowed": ["USD", "EUR"]},
    {"id": "status", "kind": "string_eq", "field": "status", "expect": "approved"}
  ]
}
```

Validation is performed at seal time and again against the sealed snapshot
during every evaluation. The second validation is defensive: it means a
corrupted or manually altered stored value cannot produce `satisfied`.

Ruleset bounds:

| Constraint | Bound |
| --- | --- |
| Rules per ruleset | 1 to 8 |
| Title length | 1 to 80 characters |
| Rule ID length | 1 to 32 characters, unique |
| Field name length | 1 to 64 characters |
| Numeric limit | Non-negative finite decimal string |
| `set_contains` values | 1 or more strings, each at most 64 characters |
| `string_eq` expected value | 1 to 128 characters |

Unknown keys are ignored. The normalized document contains only `schema`,
`title`, and the supported rule fields. Normalization makes the stored snapshot
stable and removes irrelevant input variation.

## Request schema

A request is a JSON object with flat values. Accepted values are:

- strings;
- integers;
- finite floats.

Rejected values are:

- booleans (Python treats `bool` as an `int` subclass, so this is checked
  explicitly);
- `null`;
- arrays;
- nested objects;
- non-finite JSON constants (`NaN`, `Infinity`, `-Infinity`).

Missing fields are not malformed requests. They are handled by the evaluator as
`unresolved` when a rule needs the field.

## Strict JSON parsing

`_decode_json` uses `json.loads` with two hardening hooks:

- `parse_constant` rejects `NaN`, `Infinity`, and `-Infinity`.
- `object_pairs_hook` rejects duplicate keys instead of accepting the parser's
  last-key-wins behavior.

Duplicate-key rejection matters because a ruleset or request with repeated keys
is ambiguous. Rejecting it keeps the sealed snapshot and the request a single
reproducible document.

## Exact decimal comparison

Numeric rules must be exact. Using binary floating point would make boundary
cases depend on representation details and would weaken cross-validator
agreement.

`_parse_decimal` converts an accepted value into:

```text
(negative, digits, scale)
```

The mathematical value is:

```text
(-1 if negative else 1) * int(digits) * 10 ** scale
```

`digits` has no leading zeros and no trailing zeros except for the single digit
`"0"`. The parser accepts:

- optional `+` or `-`;
- an integer part;
- an optional fraction;
- an optional exponent with at most six digits.

It rejects malformed strings, non-ASCII digits, multiple decimal points, empty
exponents, and non-finite values. `_compare_decimals` compares sign, then
magnitude by decimal order and aligned digits, so equality and ordering are
exact without floating point.

The numeric rule limit must be a **string**. Request numbers may be strings or
JSON numbers. This asymmetry is deliberate: the sealed policy has one canonical
representation, while request producers may use ordinary JSON numbers.

## Evaluation

The pure evaluator is `_evaluate(ruleset_text, request_text)`. It:

1. Validates and normalizes the sealed ruleset.
2. Parses the request.
3. Evaluates each rule in order.
4. Emits one check record per rule: `{"id": ..., "pass": ...}`.
5. Computes the fold with explicit precedence.

Check behavior:

| Situation | Check `pass` | Fold effect |
| --- | --- | --- |
| Comparable value passes | `true` | None |
| Comparable value fails | `false` | `violated` if nothing is unresolved |
| Field missing | `false` | `unresolved` |
| Incompatible value type or malformed number | `false` | `unresolved` |
| Malformed ruleset | no checks | `unresolved` |
| Malformed request | no checks | `unresolved` |

Fold precedence:

```text
any unresolved -> "unresolved"
else all checks true -> "satisfied"
else -> "violated"
```

This makes unresolved dominate violated and violated dominate satisfied. A
missing field cannot be silently treated as a passing check, and an
incompatible type cannot be treated as a policy failure with a positive path.

## Consensus

Storage is read before consensus:

```python
sealed_ruleset = self.rulesets.get(ruleset_id)
ruleset_snapshot = sealed_ruleset
request_snapshot = request_json
```

The leader and validator closures capture only those strings. They do not
capture `self`, so validators cannot read or write contract storage while
re-deriving the decision.

`gl.vm.run_nondet` is called with:

- `leader_fn`: returns the full evaluator payload;
- `validator_fn`: independently evaluates the same snapshots and compares the
  canonical JSON of the leader's `result.calldata` against its own canonical
  expected payload.

The comparison is exact over:

- `ruleset_ok`;
- `request_ok`;
- the complete ordered `checks` list, including every ID and boolean;
- `fold`.

A leader error, a non-return result, a non-dictionary payload, a missing field, a
tampered check, or a changed fold is rejected. A shape-only payload is rejected.
Any exception in the validator returns `False` (disagreement), never `True`.

After consensus, the accepted payload is persisted. The contract then writes:

- the receipt under `receipts[receipt_id]`;
- the latest pointer under `ruleset_to_latest[ruleset_id]`;
- the increment to `receipt_counter`.

A second request is never blocked. Each accepted request creates a new receipt;
the latest pointer advances, while earlier receipts remain readable.

## Receipt schema

```json
{
  "schema": "prr.receipt.v1",
  "receipt_id": "rc-1",
  "ruleset_id": "rs-1",
  "ruleset_ok": true,
  "request_ok": true,
  "request": {"amount": "250.50", "currency": "USD", "status": "approved"},
  "checks": [
    {"id": "amount", "pass": true},
    {"id": "currency", "pass": true},
    {"id": "status", "pass": true}
  ],
  "fold": "satisfied"
}
```

`request` is the parsed request object when `request_ok` is true, otherwise
`null`. Checks are empty when the request is malformed. The receipt schema is
versioned so consumers can reject unknown shapes.

## Views and errors

- `get_ruleset` returns the sealed JSON or raises `ruleset not found`.
- `get_receipt` returns the receipt JSON or raises `receipt not found`.
- `get_latest_for_ruleset` raises `ruleset not found` for an unknown ruleset,
  and returns `""` before the first receipt.
- Count views return `u256`.

All user-facing failures use `gl.vm.UserError`. Malformed requests do **not**
revert `request`; they produce an `unresolved` receipt. A missing ruleset is an
explicit revert because there is no policy to evaluate.

## Why no model

The contract's decision surface is intentionally limited to operator comparisons
over sealed fields. There is no model prompt, classification, summarization,
scoring, voting, or confidence threshold. As a result:

- identical inputs always produce identical outputs;
- a validator can reproduce the exact payload without model access;
- policy prose cannot leak into the verdict;
- malformed input has no path to a positive fold;
- there is no partial-credit or percentage state to manipulate.

## Limits and non-goals

- Maximum eight rules per ruleset keeps evaluation and payload size bounded.
- Rulesets are immutable; policy changes use a new ruleset.
- There is no deletion, amendment, or receipt mutation.
- There are no payable methods, transfers, or external calls.
- There is no natural-language parsing. A semantic policy must be reduced to
  the four supported structural checks before sealing.
- The contract does not validate the real-world truth of request values. It
  records that a sealed policy was applied to the submitted data.

## Testing strategy

Direct-mode tests exercise the contract in the native Python runner. They cover
all validation branches, all check kinds, fold boundaries, malformed input,
missing fields, newer receipts, unknown IDs, and consensus behavior. The
consensus test captures the validator and runs it against:

- no leader result;
- the honest payload;
- a changed fold;
- a changed check;
- a shape-only payload;
- a leader error.

Only the honest payload is accepted. The tampering cases must all fail.
