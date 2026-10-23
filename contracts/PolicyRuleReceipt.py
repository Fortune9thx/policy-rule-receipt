# v0.3.0
# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }

from genlayer import *
import json
import typing
import genlayer as gl
from genlayer.storage import TreeMap


# PolicyRuleReceipt is a deterministic ruleset evaluator wrapped in a consensus
# receipt. A ruleset is sealed once, at creation time. A request is then checked
# against that sealed ruleset, and a receipt is written only after every
# validator has independently re-derived the same checks and the same fold.
#
# The model is deliberately never asked whether a request "looks compliant".
# Policy prose is not classified, summarized, or scored. The only inputs to the
# decision are the sealed rule fields and the request fields. This keeps the
# decision surface small, auditable, and reproducible.
#
# There are four pure check kinds:
#   number_lte, number_gte, set_contains, string_eq
#
# A check is evaluated by ordinary Python code over extracted values. The fold
# (satisfied / violated / unresolved) is computed deterministically from the
# list of check outcomes. No EXPANDS, RESTRICTS, ALLOW, DENY, percentage score,
# confidence band, or model output participates in the fold.

RULESET_SCHEMA = "prr.ruleset.v1"
RECEIPT_SCHEMA = "prr.receipt.v1"
MAX_TITLE_LENGTH = 80
MIN_RULES = 1
MAX_RULES = 8
MAX_RULE_ID_LENGTH = 32
MAX_FIELD_LENGTH = 64
MAX_ALLOWED_LENGTH = 64
MAX_EXPECT_LENGTH = 128
CHECK_KINDS = ("number_lte", "number_gte", "set_contains", "string_eq")


def _reject_json_constant(value: str) -> typing.NoReturn:
    """Reject the non-standard JSON constants NaN, Infinity, and -Infinity."""
    raise ValueError("non-standard JSON constant: " + value)


def _unique_object(pairs: typing.List[typing.Tuple[str, typing.Any]]) -> typing.Dict[str, typing.Any]:
    """Build an object while rejecting duplicate keys.

    Duplicate keys make a JSON document ambiguous. Rejecting them keeps the
    sealed ruleset and the request a single, reproducible snapshot instead of
    relying on a parser's last-key-wins behavior.
    """
    result: typing.Dict[str, typing.Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _decode_json(document: str) -> typing.Any:
    """Decode strict JSON using only deterministic Python library behavior."""
    if not isinstance(document, str):
        raise ValueError("document must be a string")
    return json.loads(
        document,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_unique_object,
    )


def _canonical(value: typing.Any) -> str:
    """Canonical JSON used for exact leader/validator payload comparison."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _is_ascii_digits(text: str) -> bool:
    """Return true only for a non-empty run of ASCII digits.

    str.isdigit() accepts non-ASCII digit characters. The comparison code below
    uses ASCII ordering directly, so the parser intentionally accepts only the
    same characters that its comparison routine understands.
    """
    if len(text) == 0:
        return False
    for character in text:
        if character < "0" or character > "9":
            return False
    return True


def _parse_decimal(value: typing.Any) -> typing.Optional[typing.Tuple[bool, str, int]]:
    """Parse a JSON string or number into an exact decimal representation.

    The returned tuple is (negative, digits, scale), where the numeric value is
    ``(-1 if negative else 1) * int(digits) * 10 ** scale`` and ``digits`` has
    no leading or trailing zeros (except the single digit "0"). This avoids
    binary floating point while still accepting ordinary decimal strings and
    JSON numbers. Returns None when the value is not a finite decimal.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, float):
        if value != value or value == float("inf") or value == float("-inf"):
            return None
        text = repr(value)
    elif isinstance(value, str):
        text = value
    else:
        return None

    if len(text) == 0:
        return None

    negative = False
    if text[0] == "+" or text[0] == "-":
        negative = text[0] == "-"
        text = text[1:]
    if len(text) == 0:
        return None

    exponent = 0
    exponent_position = -1
    for index in range(len(text)):
        character = text[index]
        if character == "e" or character == "E":
            if exponent_position != -1:
                return None
            exponent_position = index
    if exponent_position != -1:
        mantissa = text[:exponent_position]
        exponent_text = text[exponent_position + 1:]
        exponent_negative = False
        if len(exponent_text) > 0 and (exponent_text[0] == "+" or exponent_text[0] == "-"):
            exponent_negative = exponent_text[0] == "-"
            exponent_text = exponent_text[1:]
        if not _is_ascii_digits(exponent_text):
            return None
        if len(exponent_text) > 6:
            return None
        exponent = int(exponent_text)
        if exponent_negative:
            exponent = -exponent
    else:
        mantissa = text

    if mantissa.count(".") > 1:
        return None
    if "." in mantissa:
        whole, fraction = mantissa.split(".")
    else:
        whole, fraction = mantissa, ""

    if whole == "":
        whole = "0"
    if not _is_ascii_digits(whole):
        return None
    if fraction != "" and not _is_ascii_digits(fraction):
        return None
    if whole == "0" and fraction == "":
        return (False, "0", 0)

    digits = (whole + fraction).lstrip("0")
    if digits == "":
        return (False, "0", 0)

    scale = exponent - len(fraction)
    while len(digits) > 1 and digits[-1] == "0":
        digits = digits[:-1]
        scale += 1
    return (negative, digits, scale)


def _compare_magnitudes(
    left: typing.Tuple[bool, str, int],
    right: typing.Tuple[bool, str, int],
) -> int:
    """Compare the absolute magnitudes of two parsed decimals."""
    left_digits = left[1]
    right_digits = right[1]
    left_order = len(left_digits) + left[2]
    right_order = len(right_digits) + right[2]
    if left_order != right_order:
        return 1 if left_order > right_order else -1
    width = max(len(left_digits), len(right_digits))
    left_aligned = left_digits + ("0" * (width - len(left_digits)))
    right_aligned = right_digits + ("0" * (width - len(right_digits)))
    if left_aligned == right_aligned:
        return 0
    return 1 if left_aligned > right_aligned else -1


def _compare_decimals(
    left: typing.Tuple[bool, str, int],
    right: typing.Tuple[bool, str, int],
) -> int:
    """Compare two parsed decimals, returning -1, 0, or 1."""
    if left[0] != right[0]:
        return -1 if left[0] else 1
    magnitude = _compare_magnitudes(left, right)
    if left[0]:
        return -magnitude
    return magnitude


def _validate_ruleset(ruleset_json: str) -> typing.Dict[str, typing.Any]:
    """Validate and normalize a ruleset document.

    This function is pure. It is used when the ruleset is sealed and again by
    every consensus participant over the sealed snapshot, so a malformed
    ruleset can never be mistaken for a satisfied one.
    """
    document = _decode_json(ruleset_json)
    if not isinstance(document, dict):
        raise ValueError("ruleset must be a JSON object")
    if document.get("schema") != RULESET_SCHEMA:
        raise ValueError("ruleset schema must be " + RULESET_SCHEMA)

    title = document.get("title")
    if not isinstance(title, str) or len(title) == 0:
        raise ValueError("ruleset title must be a non-empty string")
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError("ruleset title must be at most 80 characters")

    rules = document.get("rules")
    if not isinstance(rules, list):
        raise ValueError("ruleset rules must be an array")
    if len(rules) < MIN_RULES or len(rules) > MAX_RULES:
        raise ValueError("ruleset must contain between 1 and 8 rules")

    normalized_rules: typing.List[typing.Dict[str, typing.Any]] = []
    seen_ids: typing.Dict[str, bool] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("each rule must be a JSON object")

        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or len(rule_id) == 0:
            raise ValueError("rule id must be a non-empty string")
        if len(rule_id) > MAX_RULE_ID_LENGTH:
            raise ValueError("rule id must be at most 32 characters")
        if rule_id in seen_ids:
            raise ValueError("rule ids must be unique")
        seen_ids[rule_id] = True

        kind = rule.get("kind")
        if kind not in CHECK_KINDS:
            raise ValueError("rule kind is not supported")

        field = rule.get("field")
        if not isinstance(field, str) or len(field) == 0:
            raise ValueError("rule field must be a non-empty string")
        if len(field) > MAX_FIELD_LENGTH:
            raise ValueError("rule field must be at most 64 characters")

        normalized: typing.Dict[str, typing.Any] = {
            "id": rule_id,
            "kind": kind,
            "field": field,
        }

        if kind == "number_lte" or kind == "number_gte":
            limit = rule.get("limit")
            parsed_limit = _parse_decimal(limit)
            if not isinstance(limit, str):
                raise ValueError("numeric rule limit must be a number string")
            if parsed_limit is None or parsed_limit[0]:
                raise ValueError("numeric rule limit must be non-negative")
            normalized["limit"] = limit
        elif kind == "set_contains":
            allowed = rule.get("allowed")
            if not isinstance(allowed, list) or len(allowed) == 0:
                raise ValueError("set_contains allowed must be a non-empty array")
            normalized_allowed: typing.List[str] = []
            for item in allowed:
                if not isinstance(item, str):
                    raise ValueError("set_contains allowed values must be strings")
                if len(item) > MAX_ALLOWED_LENGTH:
                    raise ValueError("set_contains allowed values must be at most 64 characters")
                normalized_allowed.append(item)
            normalized["allowed"] = normalized_allowed
        else:
            expect = rule.get("expect")
            if not isinstance(expect, str) or len(expect) == 0:
                raise ValueError("string_eq expect must be a non-empty string")
            if len(expect) > MAX_EXPECT_LENGTH:
                raise ValueError("string_eq expect must be at most 128 characters")
            normalized["expect"] = expect

        normalized_rules.append(normalized)

    return {"schema": RULESET_SCHEMA, "title": title, "rules": normalized_rules}


def _parse_request(request_json: str) -> typing.Tuple[bool, typing.Dict[str, typing.Any]]:
    """Parse a request into a flat field map.

    A request is well-formed only when it is a JSON object whose values are
    strings or finite numbers. Arrays, objects, booleans, and null are not
    field values here. Missing required fields are handled later as unresolved
    checks rather than as satisfied ones.
    """
    try:
        document = _decode_json(request_json)
    except Exception:
        return (False, {})
    if not isinstance(document, dict):
        return (False, {})
    for key in document:
        value = document[key]
        if isinstance(value, bool):
            return (False, {})
        if isinstance(value, str):
            continue
        if isinstance(value, int):
            continue
        if isinstance(value, float):
            if value != value or value == float("inf") or value == float("-inf"):
                return (False, {})
            continue
        return (False, {})
    return (True, document)


def _evaluate_rule(rule: typing.Dict[str, typing.Any], value: typing.Any) -> typing.Optional[bool]:
    """Evaluate one pure check.

    Returns True or False for a comparable value, and None when the value has a
    type or shape that makes the rule impossible to evaluate. None becomes an
    unresolved outcome, never a satisfied one.
    """
    kind = rule["kind"]
    if kind == "number_lte" or kind == "number_gte":
        try:
            parsed_value = _parse_decimal(value)
            parsed_limit = _parse_decimal(rule["limit"])
        except Exception:
            return None
        if parsed_value is None or parsed_limit is None:
            return None
        comparison = _compare_decimals(parsed_value, parsed_limit)
        if kind == "number_lte":
            return comparison <= 0
        return comparison >= 0
    if kind == "set_contains":
        if not isinstance(value, str):
            return None
        return value in rule["allowed"]
    if kind == "string_eq":
        if not isinstance(value, str):
            return None
        return value == rule["expect"]
    return None


def _evaluate(ruleset_text: str, request_text: str) -> typing.Dict[str, typing.Any]:
    """Derive the full consensus payload from two local snapshots.

    This function is the whole decision procedure. Both the leader and every
    validator call it independently. It performs no storage access and no
    network access. The fold is computed from the check booleans after all
    checks have been evaluated, so there is no model-provided verdict and no
    score that could drift between nodes.
    """
    payload: typing.Dict[str, typing.Any] = {
        "ruleset_ok": False,
        "request_ok": False,
        "checks": [],
        "fold": "unresolved",
    }

    try:
        ruleset = _validate_ruleset(ruleset_text)
    except Exception:
        # A malformed sealed ruleset cannot support any positive receipt.
        return payload

    payload["ruleset_ok"] = True

    request_ok, request = _parse_request(request_text)
    if not request_ok:
        # A malformed request cannot produce "satisfied".
        return payload

    payload["request_ok"] = True

    checks: typing.List[typing.Dict[str, typing.Any]] = []
    all_passed = True
    any_unresolved = False
    for rule in ruleset["rules"]:
        field = rule["field"]
        if field not in request:
            # Missing required data is unresolved, not a policy violation.
            checks.append({"id": rule["id"], "pass": False})
            any_unresolved = True
            continue
        outcome = _evaluate_rule(rule, request[field])
        if outcome is None:
            # An incompatible value is malformed for this rule.
            checks.append({"id": rule["id"], "pass": False})
            any_unresolved = True
            continue
        checks.append({"id": rule["id"], "pass": bool(outcome)})
        if not outcome:
            all_passed = False

    payload["checks"] = checks
    if any_unresolved:
        payload["fold"] = "unresolved"
    elif all_passed:
        payload["fold"] = "satisfied"
    else:
        payload["fold"] = "violated"
    return payload


class PolicyRuleReceipt(gl.contract.Contract):
    """Sealed rulesets and their deterministic evaluation receipts.

    Storage is intentionally limited to TreeMap[str, str]. Every record is a
    canonical JSON string. There are no funds, scores, reputation values,
    voting objects, amendments, or partial-credit fields.
    """

    rulesets: TreeMap[str, str]
    receipts: TreeMap[str, str]
    ruleset_to_latest: TreeMap[str, str]
    ruleset_counter: u256
    receipt_counter: u256

    def __init__(self):
        # TreeMap fields are storage-backed containers allocated by GenVM from
        # their annotations. They must not be constructed inside __init__.
        self.ruleset_counter = u256(0)
        self.receipt_counter = u256(0)

    @gl.public.write
    def open_ruleset(self, ruleset_json: str) -> str:
        """Validate, seal, and register a ruleset.

        Sealing normalizes the document before storage. Later requests re-parse
        the stored snapshot, so they evaluate exactly the sealed rules rather
        than whatever text a caller might send again.
        """
        try:
            normalized = _validate_ruleset(ruleset_json)
        except Exception as error:
            raise gl.vm.UserError("invalid ruleset: " + str(error))

        next_index = int(self.ruleset_counter) + 1
        self.ruleset_counter = u256(next_index)
        ruleset_id = "rs-" + str(next_index)
        self.rulesets[ruleset_id] = _canonical(normalized)
        return ruleset_id

    @gl.public.write
    def request(self, ruleset_id: str, request_json: str) -> str:
        """Evaluate a request against a sealed ruleset and write a receipt.

        Storage is read before the non-deterministic block. The leader and every
        validator then receive only immutable local snapshots of the sealed
        ruleset text and the request text. No validator touches self.*. After
        consensus, the accepted payload is persisted and the ruleset's latest
        pointer is updated. A second request is never blocked.
        """
        sealed_ruleset = self.rulesets.get(ruleset_id)
        if sealed_ruleset is None:
            raise gl.vm.UserError("ruleset not found")

        # These two strings are local snapshots. The closures below deliberately
        # do not capture self, so validators cannot read or write storage while
        # re-deriving the decision.
        ruleset_snapshot = sealed_ruleset
        request_snapshot = request_json

        def leader_fn() -> typing.Dict[str, typing.Any]:
            return _evaluate(ruleset_snapshot, request_snapshot)

        def validator_fn(result: gl.vm.Result) -> bool:
            try:
                if not isinstance(result, gl.vm.Return):
                    return False
                expected = _evaluate(ruleset_snapshot, request_snapshot)
                actual = result.calldata
                if not isinstance(actual, dict):
                    return False
                # Exact canonical comparison: matching JSON shape alone is not
                # enough. Every check id, every boolean, and the fold must be
                # independently reproduced. Any exception is disagreement.
                return _canonical(actual) == _canonical(expected)
            except Exception:
                return False

        payload = gl.vm.run_nondet(leader_fn, validator_fn)
        if not isinstance(payload, dict):
            raise gl.vm.UserError("consensus payload is malformed")

        next_index = int(self.receipt_counter) + 1
        self.receipt_counter = u256(next_index)
        receipt_id = "rc-" + str(next_index)

        parsed_request: typing.Any = None
        if payload.get("request_ok") is True:
            _, parsed_request = _parse_request(request_snapshot)

        receipt = {
            "schema": RECEIPT_SCHEMA,
            "receipt_id": receipt_id,
            "ruleset_id": ruleset_id,
            "ruleset_ok": payload["ruleset_ok"],
            "request_ok": payload["request_ok"],
            "request": parsed_request,
            "checks": payload["checks"],
            "fold": payload["fold"],
        }
        encoded = _canonical(receipt)
        self.receipts[receipt_id] = encoded
        self.ruleset_to_latest[ruleset_id] = receipt_id
        return receipt_id

    @gl.public.view
    def get_ruleset(self, ruleset_id: str) -> str:
        """Return the sealed ruleset JSON for an id."""
        sealed_ruleset = self.rulesets.get(ruleset_id)
        if sealed_ruleset is None:
            raise gl.vm.UserError("ruleset not found")
        return sealed_ruleset

    @gl.public.view
    def get_receipt(self, receipt_id: str) -> str:
        """Return a stored receipt JSON string by id."""
        receipt = self.receipts.get(receipt_id)
        if receipt is None:
            raise gl.vm.UserError("receipt not found")
        return receipt

    @gl.public.view
    def get_latest_for_ruleset(self, ruleset_id: str) -> str:
        """Return the latest receipt JSON for a ruleset, or "" if none."""
        if ruleset_id not in self.rulesets:
            raise gl.vm.UserError("ruleset not found")
        latest_id = self.ruleset_to_latest.get(ruleset_id)
        if latest_id is None:
            return ""
        latest = self.receipts.get(latest_id)
        if latest is None:
            return ""
        return latest

    @gl.public.view
    def get_ruleset_count(self) -> u256:
        """Return the number of sealed rulesets."""
        return self.ruleset_counter

    @gl.public.view
    def get_receipt_count(self) -> u256:
        """Return the number of written receipts."""
        return self.receipt_counter
