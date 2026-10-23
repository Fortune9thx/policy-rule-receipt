# PolicyRuleReceipt

Deterministic policy evaluation with GenLayer consensus receipts.

`PolicyRuleReceipt` seals a bounded ruleset once, evaluates a request against that
sealed snapshot using ordinary Python comparisons, and writes a receipt only after
the leader and every validator independently derive the same checks and the same
fold. A language model is never asked whether a request "looks compliant".

## Live deployment

| Item | Value |
| --- | --- |
| Network | Studio Devnet |
| Chain ID | `61997` |
| Contract | `0xdeD3Ea8d4b0B535E1Af00B7f379b47d3a785bf8f` |
| Deploy transaction | `0x5c972e94fffe964413bc842f321c694e5156cfb060f5ac5b6156aeb8324645c7` |
| Live ruleset | `rs-1` |
| Open transaction | `0x1bf025960412c7cfda73449d35c401732558ea32a771061ead17f57f84874b54` |
| Live receipt | `rc-1` |
| Request transaction | `0x9e629ce26f525398cacdacee03de9170f34d3e125d7e9ca196ddd12c8995708d` |
| Receipt fold | `satisfied` |

The live smoke test opened a three-rule invoice policy, submitted a conforming
request, waited for `FINALIZED`, and verified that `get_receipt("rc-1")` exactly
matched `get_latest_for_ruleset("rs-1")`.

```json
{
  "checks": [
    {"id": "amount", "pass": true},
    {"id": "currency", "pass": true},
    {"id": "status", "pass": true}
  ],
  "fold": "satisfied",
  "receipt_id": "rc-1",
  "request": {
    "amount": "250.50",
    "currency": "USD",
    "status": "approved"
  },
  "request_ok": true,
  "ruleset_id": "rs-1",
  "ruleset_ok": true,
  "schema": "prr.receipt.v1"
}
```

## Design goals

- **Deterministic decisions.** Rules are plain comparisons over sealed values.
  There is no model classification, score, confidence, percentage, or prose
  interpretation anywhere in the decision path.
- **Malformed is never satisfied.** A malformed ruleset or request, a missing
  field, or an incompatible value produces `unresolved`, never `satisfied`.
- **Independent validation.** Validators re-run the full evaluator over local
  snapshots and compare the exact canonical payload. They never read contract
  storage inside consensus.
- **Immutable policy snapshots.** A ruleset is validated and normalized when it
  is sealed. Later changes require a new ruleset; the old one remains intact.
- **Bounded inputs.** Rulesets are capped at eight rules and all user-visible
  strings have explicit length limits.
- **Small state surface.** Storage is only `TreeMap[str, str]` containing
  canonical JSON, plus two monotonic counters. No funds, voting, reputation, or
  partial-credit state exists.

## Checks and folds

Four pure check kinds are supported:

| Kind | Comparison |
| --- | --- |
| `number_lte` | Request number is less than or equal to the sealed limit. |
| `number_gte` | Request number is greater than or equal to the sealed limit. |
| `set_contains` | Request string is a member of the sealed allowed set. |
| `string_eq` | Request string exactly equals the sealed expected string. |

Numeric comparisons use an exact decimal representation. Binary floating point
is never used for the comparison itself.

Fold precedence is deliberate:

1. Any malformed input, missing field, or incompatible value makes the receipt
   `unresolved`.
2. Otherwise, any failed check makes it `violated`.
3. Only when every check passes is the receipt `satisfied`.

## Ruleset format

```json
{
  "schema": "prr.ruleset.v1",
  "title": "Invoice approval",
  "rules": [
    {
      "id": "amount",
      "kind": "number_lte",
      "field": "amount",
      "limit": "1000.00"
    },
    {
      "id": "currency",
      "kind": "set_contains",
      "field": "currency",
      "allowed": ["USD", "EUR"]
    },
    {
      "id": "status",
      "kind": "string_eq",
      "field": "status",
      "expect": "approved"
    }
  ]
}
```

Ruleset constraints:

- 1 to 8 rules.
- Rule IDs are non-empty, at most 32 characters, and unique.
- Rule fields are non-empty and at most 64 characters.
- `number_lte` and `number_gte` limits are non-negative number strings.
- `set_contains` requires a non-empty array of strings, each at most 64
  characters.
- `string_eq` requires a non-empty expected string of at most 128 characters.
- The title is non-empty and at most 80 characters.

Unknown keys are ignored. The normalized ruleset is what gets sealed.

## Request format

A request is a JSON object whose values are strings or finite numbers. Nested
objects, arrays, booleans, and `null` are malformed. Missing fields are allowed
but produce `unresolved` when a rule needs them.

```json
{
  "amount": "250.50",
  "currency": "USD",
  "status": "approved"
}
```

String comparison is exact and case-sensitive. Numeric request values may be
decimal strings or JSON numbers; the numeric rule limit itself must be a string
so the sealed policy has one unambiguous representation.

## Contract API

| Method | Type | Returns | Description |
| --- | --- | --- | --- |
| `open_ruleset(ruleset_json)` | write | `str` | Validate, normalize, seal, and register a ruleset. Returns `rs-N`. |
| `request(ruleset_id, request_json)` | write | `str` | Evaluate against the sealed ruleset and write `rc-N`. |
| `get_ruleset(ruleset_id)` | view | `str` | Sealed ruleset JSON. |
| `get_receipt(receipt_id)` | view | `str` | Stored receipt JSON. |
| `get_latest_for_ruleset(ruleset_id)` | view | `str` | Latest receipt JSON, or `""` before the first request. |
| `get_ruleset_count()` | view | `u256` | Number of sealed rulesets. |
| `get_receipt_count()` | view | `u256` | Number of receipts. |

Unknown IDs raise `gl.vm.UserError`. A second request never blocks an earlier
receipt; each accepted request creates a new receipt and advances the latest
pointer for that ruleset.

## Validation and consensus

When `request` runs:

1. The sealed ruleset text is read before the consensus block.
2. Leader and validators receive only immutable local snapshots of the ruleset
   and request text.
3. Both sides run the same pure evaluator. No validator touches `self.*`.
4. The validator accepts only an exact canonical match of ruleset validity,
   request validity, every check ID and boolean, and the fold.
5. After consensus, the accepted payload is persisted and the latest pointer is
   updated.

Any exception in validation or comparison returns `unresolved` rather than a
positive decision. A corrupted sealed ruleset also returns `unresolved`.

## Storage

The contract uses `TreeMap[str, str]` for:

- `rulesets`: `ruleset_id ->` canonical ruleset JSON.
- `receipts`: `receipt_id ->` canonical receipt JSON.
- `ruleset_to_latest`: `ruleset_id ->` latest receipt ID.

The `TreeMap` fields are annotation-declared storage containers. In the target
runtime they are allocated by GenVM and must not be constructed inside
`__init__`; doing so would replace the storage-backed object. Only the two
counters are initialized in the constructor.

## Development

Requirements are pinned in `requirements-test.txt`.

```powershell
python -m pip install -r requirements-test.txt
$env:PYTHONIOENCODING = "utf-8"
$env:GENVM_VERSION = "v0.6.0-rc8"
gltest tests/direct -v
genvm-lint check --json contracts/PolicyRuleReceipt.py
```

Expected result: 29 passing tests and a successful lint/validation report with
7 methods, 5 view methods, 2 write methods, and 0 constructor parameters.

The test suite covers:

- malformed rulesets: schema, title, rule count, kind, duplicate IDs, duplicate
  JSON keys, non-finite JSON constants, negative limits, empty rule lists,
  invalid limits, empty sets, and empty strings;
- all four check kinds, including boundary equality;
- malformed requests, nested values, missing fields, wrong numeric types,
  duplicate JSON keys, non-finite JSON constants, and non-ASCII digits;
- honest leader acceptance and tampered leader rejection;
- second receipts and latest-pointer behavior;
- unknown ruleset and receipt errors;
- empty latest state before any request.

Direct tests use the GenVM runner pinned in the contract header. The runner is
available in GenVM `v0.6.0-rc8`. The `conftest.py` file contains a Windows-only
patch for a temporary-file unlink issue in direct mode; it does not change
contract behavior.

## Deployment

The live deployment is on **Studio Devnet**, not Bradbury. Deployment requires a
funded Studio Devnet account and a complete fee distribution. The GenLayer CLI
used for this deployment required the full `--fees` JSON object rather than only
`--fee-value`; reads and writes after deployment were performed with the
`genlayer-py` SDK because the CLI cannot pass a raw JSON string argument without
adding quoting.

Exact deployment and smoke-test transactions are recorded in
`PORTAL_SUBMISSION.md`.

## Security and limits

- This repository is production-oriented but has not been independently
  audited. Review the contract, tests, and assumptions before holding value.
- Rulesets are structural policies, not natural-language interpretation. A
  policy that requires semantic judgment is outside this contract's scope.
- All rulesets, requests, receipts, and transaction data are public on-chain.
  Never submit secrets or personal data.
- A ruleset is immutable once sealed. Create a new ruleset to change policy.
- There are no external calls, no payable methods, and no model inference.
- Consensus protects against a single dishonest leader or validator only within
  GenVM's validator assumptions; it does not guarantee real-world truth of the
  submitted data.

See `SECURITY.md` for the threat model and `docs/DESIGN.md` for the full design.

## Repository layout

```text
contracts/PolicyRuleReceipt.py       Contract implementation
tests/direct/                        Direct-mode tests and Windows test patch
docs/DESIGN.md                       Design and invariants
docs/WHY_THIS_PASSES_REVIEW.md       Requirement-by-requirement review map
PORTAL_SUBMISSION.md                 Live deployment and smoke evidence
SECURITY.md                          Threat model and security properties
CHANGELOG.md                         Release history
.github/workflows/ci.yml             Linux CI for lint and tests
requirements-test.txt                Pinned test toolchain
```

## License

MIT. See `LICENSE`.
