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


@pytest.mark.parametrize("field", ["jurisdiction", "worker_type"])
def test_general_cap_requires_decisive_scope_fields(field):
    result = evaluate([rule("current", 250)], workflow_id="general", **{field: None})
    assert result["query_status"] == "needs_review"
    assert "input:" + field in result["missing_evidence_categories"]


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
        "expense_amount",
        "currency",
    ],
)
def test_missing_required_case_context_requests_review(field):
    result = evaluate([rule("cap", 250), verified()], **{field: None})
    assert result["case_outcome"] == "undetermined"
    assert result["query_status"] == "needs_review"


def test_p17_case_without_optional_cost_centre_is_compared():
    result = evaluate([rule("cap", 150), verified()], cost_centre=None)
    assert result["query_status"] == "answered"
    assert result["case_outcome"] == "exceeds_documented_limits"


def test_missing_date_general_cap_requests_structured_review():
    result = evaluate([rule("cap", 250)], workflow_id="general", case_date=None)
    assert result["query_status"] == "needs_review"
    assert result["case_outcome"] == "undetermined"
    assert "input:case_date" in result["missing_evidence_categories"]


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


@pytest.fixture
def real_catalogue(tmp_path):
    from pathlib import Path

    from aspire_brain.auth import AuthService
    from aspire_brain.db import Database
    from aspire_brain.knowledge import Retriever

    data = Path(__file__).resolve().parents[2] / "data" / "demo"
    database = Database(tmp_path / "policy-fixture.db")
    database.initialize()
    database.seed(data / "manifest.json", data / "principals.json")
    return AuthService(database), Retriever(database)


def fixture_result(catalogue, principal_id="employee", **changes):
    context = {**CONTEXT, **changes}
    auth, retriever = catalogue
    principal = auth.principal(principal_id)
    scope = {
        key: context[key]
        for key in ("jurisdiction", "worker_type", "project", "cost_centre")
        if context.get(key)
    }
    rules = retriever.all_rules(principal, context["case_date"], scope)
    return PolicyEngine().evaluate(rules, context)


@pytest.mark.parametrize(
    "day,value,version",
    [
        ("2026-08-20", "200", "sg-travel-v1"),
        ("2026-08-31", "200", "sg-travel-v1"),
        ("2026-09-01", "250", "sg-travel-v2"),
        ("2026-09-10", "250", "sg-travel-v2"),
    ],
)
def test_fixture_date_selection(real_catalogue, day, value, version):
    result = fixture_result(real_catalogue, workflow_id="general", case_date=day)
    assert result["query_status"] == "answered"
    assert [(r["value"], r["version_id"]) for r in result["applied_rules"]] == [(value, version)]


def test_fixture_finance_p17_no_cost_centre(real_catalogue):
    result = fixture_result(real_catalogue, "finance_lead", cost_centre=None)
    assert result["query_status"] == "answered"
    assert result["case_outcome"] == "exceeds_documented_limits"
    assert [
        (r["value"], r["version_id"]) for r in result["applied_rules"] if r["key"] == "travel_cap"
    ] == [("150", "p17-contract-v2")]


def test_fixture_missing_and_unreadable_contract_have_same_safe_outcome(real_catalogue):
    hidden = fixture_result(real_catalogue, project="P17")
    absent = fixture_result(real_catalogue, project="P99")
    for key in ("query_status", "case_outcome", "missing_evidence_categories", "summary"):
        assert hidden[key] == absent[key]
    assert hidden["missing_evidence_categories"] == ["contract_terms"]
    assert "p17-contract" not in str(hidden)
    assert "150" not in str(hidden)


def test_fixture_conflict_detected_from_catalogue_without_top_k(real_catalogue):
    result = fixture_result(real_catalogue, workflow_id="general", cost_centre="CC-CONFLICT")
    assert result["query_status"] == "needs_review"
    assert any(
        set(conflict["rule_ids"]) == {"conflict-a-cap", "conflict-b-cap"}
        for conflict in result["conflicts"]
    )


def test_fixture_distinct_jurisdiction_and_tenant(real_catalogue):
    malaysia = fixture_result(
        real_catalogue, workflow_id="general", jurisdiction="MY", currency="MYR"
    )
    assert malaysia["query_status"] == "answered"
    assert not malaysia["conflicts"]
    assert [r["value"] for r in malaysia["applied_rules"]] == ["400"]
    other = fixture_result(real_catalogue, "other_tenant", workflow_id="general")
    assert [r["value"] for r in other["applied_rules"]] == ["75"]


def test_fixture_rules_point_to_supporting_source_passage(real_catalogue):
    result = fixture_result(real_catalogue, "finance_lead")
    for rule_row in result["applied_rules"]:
        assert rule_row["chunk_id"].endswith(":p2")
        assert rule_row["value"] in rule_row["text"]
