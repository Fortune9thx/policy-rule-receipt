# Portal submission

## Project

- **Name:** PolicyRuleReceipt
- **Repository:** https://github.com/Fortune9thx/policy-rule-receipt
- **Author:** Fortunex9 (`Fortune9thx`)
- **Version:** 1.0.0
- **License:** MIT

## Summary

`PolicyRuleReceipt` seals a bounded policy ruleset once and evaluates requests
against that exact snapshot using deterministic comparisons. It writes an
immutable receipt containing every check outcome and one of three folds:
`satisfied`, `violated`, or `unresolved`. A GenLayer leader/validator consensus
round independently re-derives the checks and fold; no language model is asked
for a policy verdict.

## Deployment

| Field | Value |
| --- | --- |
| Network | Studio Devnet |
| Chain ID | `61997` |
| Contract address | `0xdeD3Ea8d4b0B535E1Af00B7f379b47d3a785bf8f` |
| Deployment transaction | `0x5c972e94fffe964413bc842f321c694e5156cfb060f5ac5b6156aeb8324645c7` |
| Deployment sender | `0x00f42f7ad0edbd0818bd46c8e51cdb5670dde6d9` |
| Deployment fee value | `120000000000000000` wei |
| Deploy status | Finalized |
| GenVM runner | `py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng` |

Studio Devnet was used because it was available. No Bradbury deployment was
made. The deployed bytecode/source corresponds to
`contracts/PolicyRuleReceipt.py`; the deployed source matches the repository
file after normalizing line endings and the trailing newline.

## Live smoke test

The smoke test used three rule kinds, including the required numeric and
membership checks.

### Ruleset

- **Ruleset ID:** `rs-1`
- **Open transaction:** `0x1bf025960412c7cfda73449d35c401732558ea32a771061ead17f57f84874b54`
- **Open result:** `MAJORITY_AGREE`
- **Status:** Finalized

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

### Request

- **Receipt ID:** `rc-1`
- **Request transaction:** `0x9e629ce26f525398cacdacee03de9170f34d3e125d7e9ca196ddd12c8995708d`
- **Request sender:** `0xCA2DE7734D5Fa468E2d04DAfE53d23C23D8B9468`
- **Result:** `MAJORITY_AGREE`
- **Status:** Finalized
- **Fold:** `satisfied`

```json
{
  "amount": "250.50",
  "currency": "USD",
  "status": "approved"
}
```

### Receipt returned by both views

`get_receipt("rc-1")` and `get_latest_for_ruleset("rs-1")` returned identical
JSON:

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

The comparison returned `latest_matches: true`.

## Quality gates

Direct-mode tests:

```text
gltest tests/direct -v
29 passed
```

Lint and schema validation:

```text
genvm-lint check --json contracts/PolicyRuleReceipt.py
{"ok":true,"lint":{"ok":true,"passed":3},"validate":{"ok":true,
"contract":"PolicyRuleReceipt","methods":7,"view_methods":5,
"write_methods":2,"ctor_params":0}}
```

Deployed schema confirms:

- 7 methods total;
- 5 read-only methods;
- 2 write methods (`open_ruleset`, `request`);
- 0 constructor parameters.

## Review focus

- **No model classification:** decisions are pure comparisons over sealed
  fields.
- **No malformed-to-satisfied path:** malformed rulesets revert; malformed
  requests, missing fields, and incompatible values yield `unresolved`.
- **Independent validation:** validators do not access `self.*` during
  non-deterministic execution and compare the exact canonical payload.
- **State:** three `TreeMap[str, str]` records and two monotonic counters.
- **Immutable history:** every accepted request writes a new receipt and updates
  the latest pointer without overwriting older receipts.
- **Bounded inputs:** maximum eight rules and explicit string limits.

## Notes

The GenLayer CLI used for this deployment required a complete fee distribution
in `--fees`; supplying only `--fee-value` failed with
`FeeValueMustBeNonZero(1)`. The deployed and post-deployment write operations
were performed with `genlayer-py` where needed. The contract itself does not
depend on the deployment tooling.

The project has not been independently audited. See `SECURITY.md` for the threat
model and residual assumptions.
