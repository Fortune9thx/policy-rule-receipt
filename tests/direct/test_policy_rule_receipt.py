"""Direct-mode tests for PolicyRuleReceipt.

These tests run the contract in the native Python runner. Consensus behavior is
exercised with ``direct_vm.run_validator``: the captured validator is called
against the leader's honest result, against tampered results, and against a
leader error. A dishonest leader must never be accepted.
"""

import json

import pytest


CONTRACT_PATH = "contracts/PolicyRuleReceipt.py"


def _base_ruleset():
    return {
        "schema": "prr.ruleset.v1",
        "title": "Treasury transfer policy",
        "rules": [
            {"id": "amount_lte", "kind": "number_lte", "field": "amount", "limit": "100"},
            {
                "id": "action_allowed",
                "kind": "set_contains",
                "field": "action",
                "allowed": ["transfer", "swap"],
            },
            {
                "id": "destination_match",
                "kind": "string_eq",
                "field": "destination",
                "expect": "0xabc",
            },
        ],
    }


def _open(contract, ruleset=None):
    document = ruleset if ruleset is not None else _base_ruleset()
    return contract.open_ruleset(json.dumps(document))


def _request(contract, ruleset_id, **fields):
    return contract.request(ruleset_id, json.dumps(fields))


def _receipt(contract, receipt_id):
    return json.loads(contract.get_receipt(receipt_id))


def test_open_ruleset_rejects_bad_schema(direct_deploy, direct_vm):
    contract = direct_deploy(CONTRACT_PATH)
    document = _base_ruleset()
    document["schema"] = "wrong.schema.v1"
    with direct_vm.expect_revert("schema"):
        contract.open_ruleset(json.dumps(document))
    assert contract.get_ruleset_count() == 0


def test_open_ruleset_rejects_empty_title(direct_deploy, direct_vm):
    contract = direct_deploy(CONTRACT_PATH)
    document = _base_ruleset()
    document["title"] = ""
    with direct_vm.expect_revert("title"):
        contract.open_ruleset(json.dumps(document))
    assert contract.get_ruleset_count() == 0


def test_open_ruleset_rejects_too_many_rules(direct_deploy, direct_vm):
    contract = direct_deploy(CONTRACT_PATH)
    document = _base_ruleset()
    document["rules"] = [
        {"id": "rule_" + str(index), "kind": "string_eq", "field": "value", "expect": "x"}
        for index in range(9)
    ]
    with direct_vm.expect_revert("between 1 and 8"):
        contract.open_ruleset(json.dumps(document))
    assert contract.get_ruleset_count() == 0


def test_open_ruleset_rejects_bad_kind(direct_deploy, direct_vm):
    contract = direct_deploy(CONTRACT_PATH)
    document = _base_ruleset()
    document["rules"] = [
        {"id": "bad", "kind": "model_classify", "field": "action"}
    ]
    with direct_vm.expect_revert("kind"):
        contract.open_ruleset(json.dumps(document))
    assert contract.get_ruleset_count() == 0


def test_open_ruleset_rejects_duplicate_ids(direct_deploy, direct_vm):
    contract = direct_deploy(CONTRACT_PATH)
    document = _base_ruleset()
    document["rules"] = [
        {"id": "same", "kind": "string_eq", "field": "a", "expect": "x"},
        {"id": "same", "kind": "string_eq", "field": "b", "expect": "y"},
    ]
    with direct_vm.expect_revert("unique"):
        contract.open_ruleset(json.dumps(document))


def test_open_ruleset_rejects_negative_limit(direct_deploy, direct_vm):
    contract = direct_deploy(CONTRACT_PATH)
    document = _base_ruleset()
    document["rules"] = [
        {"id": "negative", "kind": "number_gte", "field": "amount", "limit": "-1"}
    ]
    with direct_vm.expect_revert("non-negative"):
        contract.open_ruleset(json.dumps(document))


def test_happy_path_is_satisfied(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    assert ruleset_id == "rs-1"

    receipt_id = _request(
        contract,
        ruleset_id,
        amount=100,
        action="transfer",
        destination="0xabc",
    )
    assert receipt_id == "rc-1"

    receipt = _receipt(contract, receipt_id)
    assert receipt["schema"] == "prr.receipt.v1"
    assert receipt["ruleset_id"] == ruleset_id
    assert receipt["ruleset_ok"] is True
    assert receipt["request_ok"] is True
    assert receipt["fold"] == "satisfied"
    assert receipt["checks"] == [
        {"id": "amount_lte", "pass": True},
        {"id": "action_allowed", "pass": True},
        {"id": "destination_match", "pass": True},
    ]

    latest = json.loads(contract.get_latest_for_ruleset(ruleset_id))
    assert latest == receipt
    assert contract.get_ruleset_count() == 1
    assert contract.get_receipt_count() == 1


def test_number_lte_failure_is_violated(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = _request(
        contract,
        ruleset_id,
        amount=101,
        action="transfer",
        destination="0xabc",
    )
    receipt = _receipt(contract, receipt_id)
    assert receipt["fold"] == "violated"
    assert receipt["checks"][0] == {"id": "amount_lte", "pass": False}
    assert receipt["checks"][1] == {"id": "action_allowed", "pass": True}
    assert receipt["checks"][2] == {"id": "destination_match", "pass": True}


def test_set_contains_failure_is_violated(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = _request(
        contract,
        ruleset_id,
        amount=10,
        action="mint",
        destination="0xabc",
    )
    receipt = _receipt(contract, receipt_id)
    assert receipt["fold"] == "violated"
    assert receipt["checks"][1] == {"id": "action_allowed", "pass": False}


def test_string_eq_failure_is_violated(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = _request(
        contract,
        ruleset_id,
        amount=10,
        action="swap",
        destination="0xdef",
    )
    receipt = _receipt(contract, receipt_id)
    assert receipt["fold"] == "violated"
    assert receipt["checks"][2] == {"id": "destination_match", "pass": False}


def test_number_gte_success_and_failure(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    document = {
        "schema": "prr.ruleset.v1",
        "title": "Minimum balance",
        "rules": [
            {"id": "minimum", "kind": "number_gte", "field": "balance", "limit": "50.5"}
        ],
    }
    ruleset_id = _open(contract, document)

    satisfied = _receipt(contract, _request(contract, ruleset_id, balance="50.50"))
    assert satisfied["fold"] == "satisfied"

    violated = _receipt(contract, _request(contract, ruleset_id, balance=50.49))
    assert violated["fold"] == "violated"


def test_malformed_request_is_unresolved(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = contract.request(ruleset_id, "{not valid json")
    receipt = _receipt(contract, receipt_id)
    assert receipt["fold"] == "unresolved"
    assert receipt["ruleset_ok"] is True
    assert receipt["request_ok"] is False
    assert receipt["checks"] == []
    assert receipt["request"] is None


def test_nested_request_value_is_unresolved(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = contract.request(
        ruleset_id,
        json.dumps(
            {
                "amount": 10,
                "action": "transfer",
                "destination": "0xabc",
                "extra": {"nested": True},
            }
        ),
    )
    receipt = _receipt(contract, receipt_id)
    assert receipt["fold"] == "unresolved"
    assert receipt["request_ok"] is False


def test_missing_field_is_unresolved(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = _request(contract, ruleset_id, amount=10, action="transfer")
    receipt = _receipt(contract, receipt_id)
    assert receipt["fold"] == "unresolved"
    assert receipt["request_ok"] is True
    assert receipt["checks"] == [
        {"id": "amount_lte", "pass": True},
        {"id": "action_allowed", "pass": True},
        {"id": "destination_match", "pass": False},
    ]


def test_wrong_numeric_type_is_unresolved(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = _request(
        contract,
        ruleset_id,
        amount="one hundred",
        action="transfer",
        destination="0xabc",
    )
    receipt = _receipt(contract, receipt_id)
    assert receipt["fold"] == "unresolved"
    assert receipt["checks"][0] == {"id": "amount_lte", "pass": False}
    assert receipt["checks"][1] == {"id": "action_allowed", "pass": True}


def test_validator_accepts_honest_leader_and_rejects_dishonest_leader(
    direct_deploy, direct_vm
):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = _request(
        contract,
        ruleset_id,
        amount=100,
        action="transfer",
        destination="0xabc",
    )
    honest = _receipt(contract, receipt_id)
    honest_payload = {
        "ruleset_ok": honest["ruleset_ok"],
        "request_ok": honest["request_ok"],
        "checks": honest["checks"],
        "fold": honest["fold"],
    }

    assert direct_vm.run_validator() is True
    assert direct_vm.run_validator(leader_result=honest_payload) is True

    flipped_fold = dict(honest_payload)
    flipped_fold["fold"] = "violated"
    assert direct_vm.run_validator(leader_result=flipped_fold) is False

    flipped_check = {
        "ruleset_ok": True,
        "request_ok": True,
        "checks": [
            {"id": "amount_lte", "pass": False},
            {"id": "action_allowed", "pass": True},
            {"id": "destination_match", "pass": True},
        ],
        "fold": "satisfied",
    }
    assert direct_vm.run_validator(leader_result=flipped_check) is False

    shape_only = {"fold": "satisfied"}
    assert direct_vm.run_validator(leader_result=shape_only) is False

    assert direct_vm.run_validator(leader_error=RuntimeError("leader failed")) is False


def test_second_request_produces_new_receipt_and_updates_latest(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)

    first_id = _request(
        contract,
        ruleset_id,
        amount=10,
        action="transfer",
        destination="0xabc",
    )
    second_id = _request(
        contract,
        ruleset_id,
        amount=999,
        action="transfer",
        destination="0xabc",
    )

    assert first_id == "rc-1"
    assert second_id == "rc-2"
    assert contract.get_receipt_count() == 2
    assert contract.get_ruleset_count() == 1

    first = _receipt(contract, first_id)
    second = _receipt(contract, second_id)
    assert first["fold"] == "satisfied"
    assert second["fold"] == "violated"

    latest = json.loads(contract.get_latest_for_ruleset(ruleset_id))
    assert latest["receipt_id"] == second_id
    assert latest["fold"] == "violated"


def test_unknown_ruleset_is_rejected(direct_deploy, direct_vm):
    contract = direct_deploy(CONTRACT_PATH)
    with direct_vm.expect_revert("ruleset not found"):
        contract.request("rs-404", json.dumps({"amount": 1}))
    with direct_vm.expect_revert("ruleset not found"):
        contract.get_ruleset("rs-404")
    with direct_vm.expect_revert("ruleset not found"):
        contract.get_latest_for_ruleset("rs-404")


def test_unknown_receipt_is_rejected(direct_deploy, direct_vm):
    contract = direct_deploy(CONTRACT_PATH)
    with direct_vm.expect_revert("receipt not found"):
        contract.get_receipt("rc-404")


def test_empty_latest_before_any_request(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    assert contract.get_latest_for_ruleset(ruleset_id) == ""
    assert contract.get_receipt_count() == 0


@pytest.mark.parametrize(
    "document",
    [
        {"schema": "prr.ruleset.v1", "title": "x", "rules": []},
        {
            "schema": "prr.ruleset.v1",
            "title": "x",
            "rules": [{"id": "a", "kind": "number_lte", "field": "amount", "limit": "1e"}],
        },
        {
            "schema": "prr.ruleset.v1",
            "title": "x",
            "rules": [{"id": "a", "kind": "set_contains", "field": "action", "allowed": []}],
        },
        {
            "schema": "prr.ruleset.v1",
            "title": "x",
            "rules": [{"id": "a", "kind": "string_eq", "field": "destination", "expect": ""}],
        },
    ],
)
def test_additional_ruleset_validation_errors(direct_deploy, direct_vm, document):
    contract = direct_deploy(CONTRACT_PATH)
    with direct_vm.expect_revert("invalid ruleset"):
        contract.open_ruleset(json.dumps(document))


def test_open_ruleset_rejects_duplicate_json_keys(direct_deploy, direct_vm):
    contract = direct_deploy(CONTRACT_PATH)
    document = (
        '{"schema":"prr.ruleset.v1","schema":"prr.ruleset.v1","title":"x",'
        '"rules":[{"id":"a","kind":"string_eq","field":"value","expect":"x"}]}'
    )
    with direct_vm.expect_revert("duplicate JSON key"):
        contract.open_ruleset(document)
    assert contract.get_ruleset_count() == 0


def test_open_ruleset_rejects_non_finite_json(direct_deploy, direct_vm):
    contract = direct_deploy(CONTRACT_PATH)
    document = (
        '{"schema":"prr.ruleset.v1","title":"x",'
        '"rules":[{"id":"a","kind":"number_lte","field":"amount","limit":NaN}]}'
    )
    with direct_vm.expect_revert("non-standard JSON constant"):
        contract.open_ruleset(document)
    assert contract.get_ruleset_count() == 0


def test_request_with_duplicate_json_key_is_unresolved(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = contract.request(
        ruleset_id,
        '{"amount":"10","amount":"20","action":"transfer","destination":"0xabc"}',
    )
    receipt = _receipt(contract, receipt_id)
    assert receipt["fold"] == "unresolved"
    assert receipt["request_ok"] is False
    assert receipt["checks"] == []


def test_request_with_non_finite_json_is_unresolved(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = contract.request(
        ruleset_id,
        '{"amount":NaN,"action":"transfer","destination":"0xabc"}',
    )
    receipt = _receipt(contract, receipt_id)
    assert receipt["fold"] == "unresolved"
    assert receipt["request_ok"] is False
    assert receipt["checks"] == []


def test_non_ascii_digits_are_not_numeric(direct_deploy):
    contract = direct_deploy(CONTRACT_PATH)
    ruleset_id = _open(contract)
    receipt_id = _request(
        contract,
        ruleset_id,
        amount="\u0661\u0660",
        action="transfer",
        destination="0xabc",
    )
    receipt = _receipt(contract, receipt_id)
    assert receipt["fold"] == "unresolved"
    assert receipt["checks"][0] == {"id": "amount_lte", "pass": False}
