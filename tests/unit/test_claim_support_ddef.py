"""D-DEF regression: the ``exact_cited_span`` release gate must retain meaning-affecting characters.

**RED before the repair.** ``providers/claims.py`` tokenised the answer and the source with
``[a-z0-9]+``, so every character outside ASCII ``a-z0-9`` was silently discarded *before* the
contiguous-span comparison. A minus sign, a ``+``/``±``/Unicode sign, a currency symbol, a
percent sign, a unit and every non-ASCII character therefore produced no token, and a mutated
claim collapsed onto the same token sequence as the cited source. The two reproduced vectors are
``SGD 250`` -> ``SGD -250`` (``v1_sign_loss``) and an inline ``无需审批`` addition
(``v2_zero_token_addition``); both were released and persisted.

Each case below declares, independently of the implementation, whether the asserted text is an
**exact quotation** of the cited source. The gate must agree with that ground truth: a case whose
ground truth is "not an exact quotation" must be *refused*, and a case that genuinely is an exact
quotation (including a Unicode one that occurs in the source) must be *accepted*. The controls
for a changed number, negation, entity order and the exact quotation were already correct before
the repair and must stay correct after it.

These assertions are deliberately about the *release decision* only. The reported lexical-overlap
ratio is a diagnostic proxy and is asserted separately to be non-binding.
"""

from __future__ import annotations

import pytest

from aspire_brain.providers.claims import evaluate_claim_support

CID = "sg-travel-v2:p2"
LOCATOR = "Fictional demo: sg-travel (sg-travel-v2) \u00b7 paragraph 2"

#: The cited source used by the 5A/5B D-DEF probe (two sentences).
CAP_SOURCE = (
    "Singapore contractor travel cap: SGD 250 per claim from 1 September 2026. "
    "This approved version explicitly supersedes v1 for its effective dates."
)
#: A source carrying a currency code, a percentage and a unit.
RULE_SOURCE = (
    "Fictional claim rule: the cap is SGD 250 per claim, a 50% advance is permitted, "
    "and the luggage limit is 30 kg."
)
#: A source whose exact text contains non-ASCII characters.
UNICODE_SOURCE = "Fictional rule: \u65e0\u9700\u5ba1\u6279 is required for amounts below SGD 250."

# (case id, source, asserted text, is_exact_quotation)
CASES = [
    # --- exact quotations: must be accepted ------------------------------------------------
    ("control_exact_quote", CAP_SOURCE, CAP_SOURCE, True),
    ("control_exact_unicode_quote", UNICODE_SOURCE, UNICODE_SOURCE, True),
    ("control_exact_unicode_subspan", UNICODE_SOURCE,
     "\u65e0\u9700\u5ba1\u6279 is required for amounts below SGD 250.", True),
    # --- reproduced false accepts: must be refused -----------------------------------------
    ("v1_sign_loss", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD -250"), False),
    ("v2_zero_token_addition", CAP_SOURCE, CAP_SOURCE.replace("2026.", "2026 \u65e0\u9700\u5ba1\u6279."), False),
    # --- ASCII and Unicode signs: must be refused ------------------------------------------
    ("sign_ascii_plus", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD +250"), False),
    ("sign_unicode_minus_u2212", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u2212250"), False),
    ("sign_unicode_en_dash", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u2013250"), False),
    ("sign_unicode_plus_minus", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u00b1250"), False),
    ("sign_unicode_ge", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u2265250"), False),
    # --- currency symbols and a dropped currency code: must be refused ---------------------
    ("currency_dollar_symbol", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD $250"), False),
    ("currency_yen_symbol", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u00a5250"), False),
    ("currency_euro_symbol", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \u20ac250"), False),
    ("currency_code_dropped", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "250"), False),
    # --- percentage symbol: must be refused ------------------------------------------------
    ("percent_sign_dropped", RULE_SOURCE, RULE_SOURCE.replace("50% advance", "50 advance"), False),
    # --- units: must be refused ------------------------------------------------------------
    ("unit_dropped", RULE_SOURCE, RULE_SOURCE.replace("30 kg", "30"), False),
    ("unit_nonascii_ligature", RULE_SOURCE, RULE_SOURCE.replace("30 kg", "30\u338f"), False),
    # --- non-ASCII additions and substitutions: must be refused ----------------------------
    ("nonascii_word_substitution", RULE_SOURCE,
     RULE_SOURCE.replace("luggage limit", "luggage \u9650\u5236"), False),
    ("nonascii_fullwidth_digits", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD \uff12\uff15\uff10"), False),
    ("nonascii_fullwidth_punct", CAP_SOURCE, CAP_SOURCE.replace("cap:", "cap\uff1a"), False),
    ("nonascii_cjk_substitution", UNICODE_SOURCE,
     UNICODE_SOURCE.replace("\u65e0\u9700\u5ba1\u6279", "\u9700\u5ba1\u6279"), False),
    # --- controls that were already refused and must stay refused --------------------------
    ("control_numeric_change", CAP_SOURCE, CAP_SOURCE.replace("SGD 250", "SGD 900"), False),
    ("control_negation", CAP_SOURCE,
     CAP_SOURCE.replace("explicitly supersedes", "does not supersede"), False),
    ("control_entity_swap", CAP_SOURCE,
     CAP_SOURCE.replace("Singapore contractor", "Alice approved Bob"), False),
]


def _report(answer, *, source=CAP_SOURCE, locators=None, notices=(), citation_ids=(CID,)):
    return evaluate_claim_support(
        answer=answer, citation_ids=list(citation_ids), evidence={CID: source},
        locators=locators, notices=list(notices),
        provider_mode="offline_extractive", mode="simulated", abstained=False)


@pytest.mark.parametrize("case_id,source,claim,is_exact", CASES, ids=[row[0] for row in CASES])
def test_gate_agrees_with_ground_truth(case_id, source, claim, is_exact):
    report = _report(claim, source=source)
    assert report["all_supported"] is is_exact, (
        f"{case_id}: gate said all_supported={report['all_supported']!r} "
        f"but ground truth is exact_quotation={is_exact!r}; "
        f"reasons={[c['reason'] for c in report['claims']]}")


# ----------------------------------------------------------------------------------------
# The diagnostic overlap ratio is not the gate
# ----------------------------------------------------------------------------------------

def test_overlap_ratio_is_diagnostic_and_never_the_gate():
    # The sign-loss claim keeps every ASCII token of the source, so the lexical proxy is 1.0;
    # it must still be refused, proving the release decision does not depend on the proxy.
    claim = CAP_SOURCE.replace("SGD 250", "SGD -250")
    report = _report(claim)
    assert report["claims"][0]["support_ratio"] == 1.0
    assert report["claims"][0]["supported"] is False
    assert report["all_supported"] is False


# ----------------------------------------------------------------------------------------
# Service-owned citation labels cannot mask a changed claim
# ----------------------------------------------------------------------------------------

def test_label_with_an_exact_quote_is_accepted():
    report = _report(f"Evidence ({LOCATOR}): {CAP_SOURCE}", locators={CID: LOCATOR})
    assert report["all_supported"] is True


def test_label_cannot_mask_a_changed_claim():
    changed = CAP_SOURCE.replace("SGD 250", "SGD -250")
    report = _report(f"Evidence ({LOCATOR}): {changed}", locators={CID: LOCATOR})
    assert report["all_supported"] is False


def test_label_naming_a_non_cited_locator_is_not_stripped():
    # The label is only service formatting when it names a *cited* locator; otherwise the whole
    # sentence (label included) must be a span of the source, which it is not.
    report = _report(f"Evidence (some other locator): {CAP_SOURCE}", locators={CID: LOCATOR})
    assert report["all_supported"] is False


# ----------------------------------------------------------------------------------------
# Service-authored notices are excluded, but cannot mask a changed claim
# ----------------------------------------------------------------------------------------

def test_notice_is_excluded_without_masking_a_changed_claim():
    notice = "The documented cap is SGD 250 per claim."
    changed = CAP_SOURCE.replace("SGD 250", "SGD -250")
    report = _report(f"{notice} {changed}", notices=[notice])
    assert report["notices_excluded"] == 1
    assert report["all_supported"] is False


def test_notice_matching_is_exact_so_a_changed_notice_is_checked():
    notice = "The documented cap is SGD 250 per claim."
    # A sentence that merely resembles the notice is not excluded; it is checked as a claim.
    lookalike = "The documented cap is SGD -250 per claim."
    report = _report(f"{lookalike} {CAP_SOURCE}", notices=[notice])
    assert report["notices_excluded"] == 0
    assert report["all_supported"] is False


# ----------------------------------------------------------------------------------------
# Permitted normalisation is explicit and minimal
# ----------------------------------------------------------------------------------------

def test_case_and_whitespace_normalisation_are_permitted():
    source = "Failover is ENABLED.\nCap is 250 SGD."
    report = _report("failover is enabled. cap is 250 sgd.", source=source)
    assert report["all_supported"] is True


def test_meaning_affecting_characters_are_not_normalised_away():
    # A sign is not whitespace and not case; it must survive normalisation.
    report = _report("Cap is -250 SGD.", source="Cap is 250 SGD.")
    assert report["all_supported"] is False


def test_unicode_is_not_compatibility_folded():
    # Fullwidth digits are distinct characters, not an acceptable spelling of ASCII digits.
    report = _report("Cap is \uff12\uff15\uff10 SGD.", source="Cap is 250 SGD.")
    assert report["all_supported"] is False


def test_a_sentence_with_no_checkable_content_still_fails_closed():
    report = _report("...", source="Cap is 250 SGD.")
    assert report["claims"][0]["supported"] is False
    assert report["claims"][0]["reason"] == "no_checkable_tokens"


# Boundary vectors are expectations independent of the matching implementation.
BOUNDARY_CASES = [
    ("numeric_suffix", "The cap is SGD 250 per claim.", "50 per claim."),
    ("numeric_prefix", "250", "25"),
    ("numeric_subtoken", "250", "50"),
    ("sign_boundary", "-250", "250"),
    ("spaced_sign_boundary", "- 250", "250"),
    ("unicode_sign_boundary", "−250", "250"),
    ("currency_boundary", "$250", "250"),
    ("spaced_currency_boundary", "SGD 250", "250"),
    ("percent_boundary", "50%", "50"),
    ("spaced_percent_boundary", "50 %", "50"),
    ("unit_boundary", "30 kg", "30"),
    ("unicode_unit_boundary", "30㎏", "30"),
    ("unicode_prefix_boundary", "无需审批", "需审批"),
    ("combining_boundary", "café", "cafe"),
    ("decimal_boundary", "250.75", "250"),
    ("comma_boundary", "250,000", "250"),
    ("newline_sign_boundary", "-\n250", "250"),
    ("newline_currency_boundary", "SGD\n250", "250"),
    ("newline_unit_boundary", "30\nkg", "30"),
]


@pytest.mark.parametrize("name,source,claim", BOUNDARY_CASES,
                         ids=[row[0] for row in BOUNDARY_CASES])
def test_partial_numeric_symbol_unit_and_unicode_edges_are_refused(name, source, claim):
    report = _report(claim, source=source)
    assert report["all_supported"] is False, name
    assert report["unsupported_claims"] == 1


@pytest.mark.parametrize("source,claim", [
    ("250", "250"), ("-250", "-250"), ("50%", "50%"),
    ("30 kg", "30 kg"), ("无需审批", "无需审批"),
    ("Label: 无需审批.", "无需审批."),
    ("First. Cap: SGD -250 per claim.", "Cap: SGD -250 per claim."),
])
def test_complete_boundary_controls_remain_supported(source, claim):
    assert _report(claim, source=source)["all_supported"] is True


@pytest.mark.parametrize("source,claim", [
    ("Cap is 250 SGD.", "Cap is\n250 SGD."),
    ("Cap is\n250 SGD.", "Cap is 250\nSGD."),
    ("Rule: 无需审批.", "Rule:\n无需审批."),
    ("The rate is 50% and the limit is 30 kg.", "The rate is\n50% and the limit is\n30 kg."),
])
def test_exact_line_wrapped_quotations_keep_whitespace_normalization(source, claim):
    assert _report(claim, source=source)["all_supported"] is True


def test_line_wrapped_service_notice_is_excluded_as_a_whole():
    notice = "Fictional service notice."
    report = _report("Fictional service\nnotice. " + CAP_SOURCE, notices=[notice])
    assert report["notices_excluded"] == 1
    assert report["all_supported"] is True


def test_line_wrapping_does_not_merge_distinct_labelled_evidence_blocks():
    report = evaluate_claim_support(
        answer="From one: Cap 250\nFrom two: Rate 50%", citation_ids=["one", "two"],
        evidence={"one": "Cap 250", "two": "Rate 50%"},
        locators={"one": "one", "two": "two"}, provider_mode="offline_extractive")
    assert report["all_supported"] is True
    assert report["denominator"] == 2
    assert [claim["supporting_ids"] for claim in report["claims"]] == [["one"], ["two"]]
