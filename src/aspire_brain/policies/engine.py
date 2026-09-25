"""Evaluate explicit trusted rules. This module never interprets document prose."""

from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import combinations

SCOPE_KEYS = frozenset({"jurisdiction", "worker_type", "project", "cost_centre"})
REVIEW_ROUTE = "Finance policy reviewer; documented limits do not authorise spending."


def money(value: object) -> Decimal:
    """Accept only finite, nonnegative decimal-compatible text or numbers."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Amount must be decimal text or an integer")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid monetary amount") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("Amount must be finite and nonnegative")
    return parsed


def _scope(rule: dict) -> dict:
    return {**rule.get("version_scope", {}), **rule.get("scope", {})}


def _applicable(rule: dict, context: dict) -> bool:
    scope = _scope(rule)
    if set(scope) - SCOPE_KEYS:
        raise ValueError("Unsupported policy scope")
    return all(context.get(key) == value for key, value in scope.items())


def _overlap(left: dict, right: dict) -> bool:
    return all(value == right[key] for key, value in left.items() if key in right)


def _compatible(left: dict, right: dict) -> bool:
    return left.get("unit") == right.get("unit") and left.get("currency") == right.get("currency")


def _resolved_rules(rules: list[dict]) -> list[dict]:
    """Only explicit applicable, comparable same-key relations remove rules."""
    by_id = {rule["id"]: rule for rule in rules}
    removed = set()
    for rule in rules:
        superseded = [
            target["id"]
            for target in rules
            if rule.get("supersedes") == target.get("version_id")
            and rule.get("document_id") is not None
            and rule.get("document_id") == target.get("document_id")
        ]
        for target_id in [*rule.get("overrides", []), *superseded]:
            target = by_id.get(target_id)
            if target and rule["key"] == target["key"] and _compatible(rule, target):
                if _overlap(_scope(rule), _scope(target)):
                    removed.add(target_id)
    return [dict(rule) for rule in rules if rule["id"] not in removed]


def _conflicts(rules: list[dict]) -> list[dict]:
    conflicts = []
    for left, right in combinations(rules, 2):
        if left["key"] != right["key"] or not _overlap(_scope(left), _scope(right)):
            continue
        kind = None
        if not _compatible(left, right):
            kind = "incomparable_units_or_currency"
        elif money(left["value"]) != money(right["value"]):
            kind = "conflicting_values"
        if kind:
            conflicts.append(
                {"kind": kind, "rule_key": left["key"], "rule_ids": [left["id"], right["id"]]}
            )
    return conflicts


def _result(
    status: str,
    outcome: str,
    rules: list[dict],
    conflicts: list[dict],
    missing: list[str],
    summary: str,
) -> dict:
    return {
        "query_status": status,
        "case_outcome": outcome,
        "applied_rules": rules,
        "conflicts": conflicts,
        "missing_evidence_categories": missing,
        "review_route": REVIEW_ROUTE,
        "summary": summary,
    }


class PolicyEngine:
    """Rules supplied here must already pass tenant, ACL and effective-date selection."""

    def evaluate(self, rules: list[dict], context: dict) -> dict:
        workflow = context.get("workflow_id", "general")
        if workflow not in {"general", "contractor_travel"}:
            raise ValueError("Unsupported workflow")
        if context.get("case_date"):
            date.fromisoformat(context["case_date"])
        if context.get("expense_amount") is not None:
            money(context["expense_amount"])
        applicable = [rule for rule in rules if _applicable(rule, context)]
        for rule in applicable:
            money(rule["value"])
        resolved = _resolved_rules(applicable)
        conflicts = _conflicts(resolved)
        caps = [rule for rule in resolved if rule["key"] == "travel_cap"]
        missing = [] if caps else ["travel_cap"]
        missing += ["input:" + key for key in ("case_date", "jurisdiction", "worker_type")
                    if context.get(key) in (None, "")]
        if workflow == "contractor_travel":
            verified = any(
                rule["key"] == "contract_verified" and money(rule["value"]) == 1
                for rule in resolved
            )
            if not verified:
                missing.append("contract_terms")
            fields = (
                "project",
                "expense_amount",
                "currency",
            )
            missing += ["input:" + key for key in fields if context.get(key) in (None, "")]
        if missing:
            return _result(
                "needs_review"
                if workflow == "contractor_travel" or any(item.startswith("input:") for item in missing)
                else "insufficient_evidence",
                "undetermined",
                resolved,
                conflicts,
                missing,
                "Required evidence or case inputs cannot be verified "
                "from the evidence available to you. Request finance review.",
            )
        if conflicts:
            return _result(
                "needs_review",
                "undetermined",
                resolved,
                conflicts,
                [],
                "Available rules conflict or have incomparable units/currencies. "
                "A finance reviewer must resolve them.",
            )
        cap = caps[0]
        amount = money(cap["value"])
        summary = f"The documented cap is {cap.get('currency') or ''} {amount} per {cap['unit']}."
        if workflow == "general":
            return _result(
                "answered",
                "not_applicable",
                resolved,
                [],
                [],
                summary + " This general guidance does not verify an individual claim.",
            )
        if context["worker_type"] != "contractor" or cap["unit"] != "claim":
            return _result(
                "needs_review",
                "undetermined",
                resolved,
                [],
                [],
                "The case or policy unit is outside this contractor claim workflow.",
            )
        if context["currency"] != cap.get("currency"):
            return _result(
                "needs_review",
                "undetermined",
                resolved,
                [],
                [],
                "The claim and policy currencies are incomparable; conversion is not supported.",
            )
        outcome = (
            "within_documented_limits"
            if money(context["expense_amount"]) <= amount
            else "exceeds_documented_limits"
        )
        return _result(
            "answered",
            outcome,
            resolved,
            [],
            [],
            summary
            + " The claim "
            + ("is within" if outcome == "within_documented_limits" else "exceeds")
            + " the documented limit for the declared case scope in the available evidence. "
            + "Cost-centre-specific rules require a declared cost centre. This is not spending approval.",
        )
