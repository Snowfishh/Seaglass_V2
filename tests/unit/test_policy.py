from copy import deepcopy

import pytest

from aspire_brain.policies import PolicyEngine

CONTEXT = {
    "workflow_id": "contractor_travel",
    "case_date": "2026-09-10",
    "jurisdiction": "SG",
    "worker_type": "contractor",
    "project": "P17",
    "cost_centre": "CC-17",
    "expense_amount": "220",
    "currency": "SGD",
}


def rule(rule_id, value, **changes):
    return {
        "id": rule_id,
        "version_id": "v-" + rule_id,
        "key": "travel_cap",
        "value": str(value),
        "unit": "claim",
        "currency": "SGD",
        "scope": {"jurisdiction": "SG", "worker_type": "contractor"},
        "source_chunk_id": "v-" + rule_id + ":p1",
        "overrides": [],
        **changes,
    }


def verified():
    return rule(
        "terms", 1, key="contract_verified", unit="boolean", currency=None, scope={"project": "P17"}
    )


def evaluate(rules, **changes):
    return PolicyEngine().evaluate(rules, {**CONTEXT, **changes})


def test_general_cap_does_not_certify_case():
    result = evaluate([rule("current", 250)], workflow_id="general")
    assert result["query_status"] == "answered"
    assert result["case_outcome"] == "not_applicable"
    assert "250" in result["summary"]


def test_p17_explicit_scoped_override():
    rules = [
        rule("general", 250),
        rule("p17", 150, scope={"project": "P17"}, overrides=["general"]),
        verified(),
    ]
    result = evaluate(rules)
    assert result["case_outcome"] == "exceeds_documented_limits"
    assert not result["conflicts"]
    assert {r["id"] for r in result["applied_rules"]} == {"p17", "terms"}
    assert result["review_route"]


def test_missing_contract_terms_never_certifies_claim():
    result = evaluate([rule("general", 250)])
    assert result["query_status"] == "needs_review"
    assert result["case_outcome"] == "undetermined"
    assert result["missing_evidence_categories"] == ["contract_terms"]
    assert "hidden" not in result["summary"]


def test_overlap_without_precedence_is_true_conflict():
    result = evaluate([rule("one", 250), rule("two", 180), verified()])
    assert result["query_status"] == "needs_review"
    assert result["case_outcome"] == "undetermined"
    assert result["conflicts"][0]["kind"] == "conflicting_values"


def test_unrelated_jurisdiction_is_not_conflict():
    result = evaluate([rule("sg", 250), rule("my", 400, scope={"jurisdiction": "MY"}), verified()])
    assert result["case_outcome"] == "within_documented_limits"
    assert not result["conflicts"]


def test_override_does_not_escape_its_scope():
    result = evaluate(
        [rule("general", 250), rule("p17", 150, scope={"project": "P17"}, overrides=["general"])],
        project="P99",
        workflow_id="general",
    )
    assert [r["id"] for r in result["applied_rules"]] == ["general"]
    assert "250" in result["summary"]


@pytest.mark.parametrize(
    "amount,outcome", [("150", "within_documented_limits"), ("150.01", "exceeds_documented_limits")]
)
def test_decimal_boundary(amount, outcome):
    assert (
        evaluate([rule("cap", 150), verified()], expense_amount=amount)["case_outcome"] == outcome
    )


@pytest.mark.parametrize(
    "field",
    [
        "case_date",
        "jurisdiction",
        "worker_type",
        "project",
        "cost_centre",
        "expense_amount",
        "currency",
    ],
)
def test_missing_required_case_context_requests_review(field):
    result = evaluate([rule("cap", 250), verified()], **{field: None})
    assert result["case_outcome"] == "undetermined"
    assert result["query_status"] == "needs_review"


@pytest.mark.parametrize("amount", ["-1", "NaN", "Infinity", "-Infinity", "bad", True])
def test_invalid_money_rejected(amount):
    with pytest.raises(ValueError):
        evaluate([rule("cap", 250), verified()], expense_amount=amount)


def test_currency_incomparability_is_review_not_conflicting_value():
    result = evaluate([rule("sgd", 250), rule("usd", 150, currency="USD"), verified()])
    assert result["case_outcome"] == "undetermined"
    assert result["conflicts"][0]["kind"] == "incomparable_units_or_currency"


def test_expense_currency_mismatch_requests_review():
    result = evaluate([rule("cap", 250), verified()], currency="USD")
    assert result["case_outcome"] == "undetermined"
    assert result["query_status"] == "needs_review"


def test_equal_values_are_not_conflict():
    result = evaluate([rule("one", 250), rule("two", 250), verified()])
    assert not result["conflicts"]
    assert result["case_outcome"] == "within_documented_limits"


def test_rule_input_unchanged():
    rules = [rule("a", 250), verified()]
    before = deepcopy(rules)
    evaluate(rules)
    assert rules == before


def test_no_caps_is_insufficient_evidence():
    assert evaluate([], workflow_id="general")["query_status"] == "insufficient_evidence"


def test_rule_with_missing_scope_input_is_not_applied():
    result = evaluate(
        [rule("scoped", 10, scope={"cost_centre": "PRIVATE"})],
        workflow_id="general",
        cost_centre=None,
    )
    assert not result["applied_rules"]


def test_transitive_override_chain_resolves():
    result = evaluate(
        [
            rule("old", 100),
            rule("middle", 200, overrides=["old"]),
            rule("new", 250, overrides=["middle"]),
            verified(),
        ]
    )
    assert not result["conflicts"]
    assert {r["id"] for r in result["applied_rules"]} == {"new", "terms"}


def test_incompatible_currency_override_cannot_silently_resolve():
    result = evaluate(
        [rule("old", 250), rule("new", 150, currency="USD", overrides=["old"]), verified()]
    )
    assert result["query_status"] == "needs_review"
    assert result["conflicts"][0]["kind"] == "incomparable_units_or_currency"


def test_explicit_version_supersession_resolves_same_document():
    result = evaluate(
        [
            rule("old", 200, document_id="policy"),
            rule("new", 250, document_id="policy", supersedes="v-old"),
            verified(),
        ]
    )
    assert result["query_status"] == "answered"
    assert {r["id"] for r in result["applied_rules"]} == {"new", "terms"}


def test_supersession_does_not_resolve_different_documents():
    result = evaluate(
        [
            rule("old", 200, document_id="policy"),
            rule("new", 250, document_id="another", supersedes="v-old"),
            verified(),
        ]
    )
    assert result["query_status"] == "needs_review"
    assert result["conflicts"]
