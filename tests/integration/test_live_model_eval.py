"""The owner-run live-model evaluation, exercised offline: verdicts, pacing, stop-early, budget."""

import importlib.util
import json
import socket
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from aspire_brain.providers.live import SpendLedger

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline test attempted network access")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("live_model_run_eval",
                                                  ROOT / "eval/live_model/run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def waits(script, monkeypatch):
    recorded = []

    async def no_wait(seconds):
        recorded.append(seconds)
    monkeypatch.setattr(script, "_sleep", no_wait)
    return recorded


def report(tmp_path):
    return json.loads(next(tmp_path.glob("dry-*.json")).read_text())


# --- verdicts on run shapes like the 14 October live runs -------------------------------------

def released(case_id, *, expected="answered", status=None, **extra):
    return {"id": case_id, "expected_status": expected, "result": "released",
            "query_status": status or expected, "status_matches": (status or expected) == expected,
            "all_claims_supported": True, "forbidden_text_absent": True, "model_called": True,
            "outcome": "succeeded", "error_category": None} | extra


def limited(case_id, retry_after=None):
    return {"id": case_id, "expected_status": "answered", "result": "error", "http_status": 502,
            "model_called": True, "outcome": "failed", "error_category": "rate_limited",
            "retry_after_seconds": retry_after}


CASE_7 = released("case_7", expected=None, abstention_control="abstained")
NO_EVIDENCE = {"id": "no-evidence", "expected_status": "insufficient_evidence",
               "result": "released", "query_status": "insufficient_evidence",
               "status_matches": True, "all_claims_supported": True,
               "forbidden_text_absent": True, "model_called": False}


def test_a_run_where_most_calls_were_rate_limited_is_inconclusive_not_pass(script):
    # Like the 11:54 run: two completed, eight refused by the provider's limits.
    rows = [CASE_7, released("a"), NO_EVIDENCE, *(limited(f"r{i}") for i in range(8))]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "inconclusive"
    assert checks["completed_calls"] == "2/10"


def test_rate_limits_are_kept_apart_from_answer_quality(script):
    # Like the 12:02 run: six correct releases, four rate-limited calls.
    rows = [CASE_7, *(released(f"a{i}") for i in range(5)), NO_EVIDENCE,
            *(limited(f"r{i}", 30.0) for i in range(4))]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "inconclusive"
    assert checks["answered_share_of_model_calls"] == "6/10"
    assert checks["answered_share_of_completed_calls"] == "6/6"


def test_a_status_mismatch_fails_the_run(script):
    rows = [CASE_7, *(released(f"a{i}") for i in range(8)),
            released("wrong", expected="needs_review", status="answered"), NO_EVIDENCE]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "fail" and checks["released_status_matches_expected"] is False


def test_a_case_7_control_that_did_not_abstain_fails_the_run(script):
    rows = [released("case_7", expected=None, abstention_control="answered"),
            *(released(f"a{i}") for i in range(9)), NO_EVIDENCE]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "fail" and checks["case_7_abstention_control_abstained"] is False


def test_a_case_7_control_that_was_never_observed_leaves_the_run_inconclusive(script):
    # Case 7 is the only safety check that can go unobserved: its call was rate-limited, so
    # its abstention control never ran. Nine correct calls must not turn that into a pass.
    rows = [limited("case_7"), *(released(f"a{i}") for i in range(9)), NO_EVIDENCE]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "inconclusive"
    assert checks["case_7_abstention_control_abstained"] is None
    assert checks["completed_calls"] == "9/10"


def test_an_error_without_a_model_call_or_provider_refusal_fails_the_run(script):
    rows = [CASE_7, *(released(f"a{i}") for i in range(9)), NO_EVIDENCE,
            {"id": "broken", "expected_status": "answered", "result": "error",
             "http_status": 503, "model_called": False}]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "fail" and checks["no_unexpected_errors"] is False


def test_a_rejected_request_shape_fails_the_run(script):
    bad_request = limited("bad") | {"error_category": "http_400"}
    rows = [CASE_7, *(released(f"a{i}") for i in range(9)), NO_EVIDENCE, bad_request]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "fail" and checks["no_unexpected_errors"] is False


@pytest.mark.parametrize("category", [None, "invalid_response", "invalid_selection",
                                      "finish_length", "unknown_provider_error"])
def test_failed_sent_calls_cannot_hide_behind_enough_successful_answers(script, category):
    failed = limited("bad") | {"error_category": category}
    rows = [CASE_7, *(released(f"a{i}") for i in range(7)), NO_EVIDENCE,
            failed, {**failed, "id": "bad-2"}]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "fail"
    assert checks["no_unexpected_errors"] is False
    assert checks["completed_calls"] == "8/10"


@pytest.mark.parametrize("category", ["rate_limited", "timeout", "network_error", "http_503"])
def test_known_availability_failures_are_not_unexpected_errors(script, category):
    failed = limited("unavailable") | {"error_category": category}
    rows = [CASE_7, *(released(f"a{i}") for i in range(7)), NO_EVIDENCE,
            failed, {**failed, "id": "unavailable-2"}]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "pass"
    assert checks["no_unexpected_errors"] is True
    assert checks["completed_calls"] == "8/10"


def test_too_few_answers_among_completed_calls_fails_on_quality(script):
    abstained = {"id": "x", "expected_status": "answered", "result": "model_abstained",
                 "http_status": 422, "model_called": True, "outcome": "succeeded",
                 "error_category": None}
    rows = [CASE_7, *(released(f"a{i}") for i in range(5)), NO_EVIDENCE,
            *({**abstained, "id": f"x{i}"} for i in range(4))]
    verdict, checks = script.assess(rows, planned=10)
    assert checks["completed_calls"] == "10/10"
    assert verdict == "fail" and checks["answered_share_meets_70_percent"] is False


def test_too_few_completed_calls_leave_the_answer_share_unjudged(script):
    # The five completed calls all answered, but five cannot show 70% either way, so the
    # answer-share check is not made instead of being reported as met.
    rows = [CASE_7, *(released(f"a{i}") for i in range(4)), NO_EVIDENCE,
            *(limited(f"r{i}", 30.0) for i in range(4))]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "inconclusive"
    assert checks["completed_calls"] == "5/10"
    assert checks["answered_share_of_completed_calls"] == "5/5"
    assert checks["answered_share_meets_70_percent"] is None


def test_release_after_abstention_is_safe_but_not_a_model_selected_answer(script):
    after = released("p17", expected="needs_review") | {"result": "released_after_abstention",
                                                        "model_abstained": True}
    rows = [CASE_7, *(released(f"a{i}") for i in range(8)), after, NO_EVIDENCE]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "pass"
    assert checks["answered_share_of_completed_calls"] == "9/10"


def test_all_completed_and_answered_passes(script):
    rows = [CASE_7, *(released(f"a{i}") for i in range(9)), NO_EVIDENCE]
    verdict, checks = script.assess(rows, planned=10)
    assert verdict == "pass" and checks["answered_share_meets_70_percent"] is True


# --- the dry run, end to end -------------------------------------------------------------------

def test_a_short_rate_limit_paces_the_next_case_and_never_resends(script, waits, tmp_path):
    # retry-after 0: the patched wait does not advance the clock, so a longer value would leave
    # the ledger's cooldown in force and stop the run instead.
    assert script.main(["--out", str(tmp_path), "--simulate-429", "2:0"]) == 0
    rows = report(tmp_path)["rows"]
    called = [row for row in rows if row.get("model_called")]
    assert [row["error_category"] for row in called].count("rate_limited") == 1
    failed = next(i for i, row in enumerate(rows) if row.get("error_category") == "rate_limited")
    assert rows[failed + 1]["model_called"]       # the next case was still sent
    assert 2.0 in waits                           # retry-after 0 s + 2 s margin, pace 0
    assert len(called) == 10                      # the refused case was not sent again
    assert report(tmp_path)["result"] == "pass"


def test_a_long_rate_limit_stops_the_run_as_inconclusive(script, waits, tmp_path):
    assert script.main(["--out", str(tmp_path), "--simulate-429", "2:3600"]) == 3
    result = report(tmp_path)
    rows = result["rows"]
    failed = next(i for i, row in enumerate(rows) if row.get("error_category") == "rate_limited")
    rest = rows[failed + 1:]
    assert rest and all(row["result"] == "not_sent" and row["reason"] == "provider_rate_limited"
                        and row["model_called"] is False for row in rest)
    assert result["result"] == "inconclusive" and result["stopped_early"] == "provider_rate_limited"
    assert len([row for row in rows if row.get("model_called")]) == 2


def test_a_429_without_retry_after_on_case_7_is_inconclusive(script, waits, tmp_path):
    # Unknown cooldowns must stop the run, preserving every remaining approved request.
    assert script.main(["--out", str(tmp_path), "--simulate-429", "1"]) == 3
    result = report(tmp_path)
    assert result["result"] == "inconclusive"
    assert result["checks"]["case_7_abstention_control_abstained"] is None
    assert result["checks"]["completed_calls"] == "0/10"
    assert result["stopped_early"] == "provider_rate_limited"
    assert all(row["result"] == "not_sent" and row["model_called"] is False
               for row in result["rows"][1:])
    assert waits == []


def test_rate_limits_without_retry_after_on_every_call_are_inconclusive(script, waits, tmp_path):
    every = [f"{n}:" for n in range(1, 11)]
    args = ["--out", str(tmp_path)] + [item for n in every for item in ("--simulate-429", n)]
    assert script.main(args) == 3
    result = report(tmp_path)
    called = [row for row in result["rows"] if row.get("model_called")]
    assert len(called) == 1 and {row["error_category"] for row in called} == {"rate_limited"}
    assert result["checks"]["answered_share_of_model_calls"] == "0/1"
    assert result["checks"]["completed_calls"] == "0/10"


@pytest.mark.parametrize("retry_after", ["nan", "-1", "later", "999999999"])
def test_invalid_retry_after_stops_without_spending_more_requests(
        script, waits, tmp_path, monkeypatch, retry_after):
    calls = []

    def rejected(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": retry_after},
                              json={"error": {"type": "rate_limit_error"}})

    monkeypatch.setattr(script, "fake_transport", lambda rate_limits: httpx.MockTransport(rejected))
    assert script.main(["--out", str(tmp_path)]) == 3
    assert len(calls) == 1
    assert report(tmp_path)["spend_after"]["requests"] == 1
    assert report(tmp_path)["stopped_early"] == "provider_rate_limited"
    assert waits == []


def test_capacity_guidance_is_an_upper_bound_not_a_measured_full_run(script, tmp_path, capsys):
    assert script.main(["--out", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "45000 tokens" in output
    assert "configured upper bound" in output
    assert "No complete live run has been measured" in output
    assert "3600" not in output


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "-inf"])
def test_invalid_pacing_is_rejected_before_ledger_or_credential_access(
        script, tmp_path, monkeypatch, capsys, value):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid pacing reached ledger or credential access")

    monkeypatch.setattr(script, "SpendLedger", forbidden)
    monkeypatch.setattr(script, "load_credential", forbidden)
    out = tmp_path / "out"
    assert script.main(["--live", "--yes", f"--pace={value}", "--out", str(out)]) == 2
    assert "--pace must be finite and nonnegative" in capsys.readouterr().err
    assert not out.exists()


def test_simulated_rate_limits_are_refused_for_real_calls(script, tmp_path):
    assert script.main(["--live", "--yes", "--simulate-429", "1:5",
                        "--key", str(tmp_path / "absent.key")]) == 2


def test_a_used_up_budget_stops_a_live_run_before_any_request(script, tmp_path, monkeypatch,
                                                               capsys):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = SpendLedger(ledger_path)
    for n in range(30):
        ledger.reserve(f"earlier-{n}", Decimal("0.001"))
    before = ledger_path.read_bytes()
    monkeypatch.setattr(script, "LEDGER", ledger_path)
    # No key file exists: the budget check must stop the run before the key is even looked at.
    assert script.main(["--live", "--yes", "--key", str(tmp_path / "absent.key"),
                        "--out", str(tmp_path / "out")]) == 2
    assert ledger_path.read_bytes() == before
    assert "budget" in capsys.readouterr().err.lower()
    assert not (tmp_path / "out").exists()


# --- the 15 October batch approval ------------------------------------------------------------

def test_the_batch_has_its_own_ledger_and_never_the_used_up_one(script):
    assert script.BATCH_MAX_REQUESTS == 10
    assert script.BATCH_MAX_USD == Decimal("0.01")
    assert script.LEDGER != ROOT / "var" / "provider" / "live-ledger.jsonl"
    assert script.LEDGER.parent == ROOT / "var" / "provider"


def test_a_full_batch_fits_the_approval_at_full_reservation(script):
    per_call = script.reserve_budget(script.EVAL_CONFIG, script.approved_rates()).reservation_usd
    assert per_call * script.BATCH_MAX_REQUESTS <= script.BATCH_MAX_USD
    assert (script.EVAL_CONFIG.input_token_cap, script.EVAL_CONFIG.output_token_cap,
            script.EVAL_CONFIG.reasoning_token_cap) == (4000, 200, 300)


def test_the_dry_run_uses_the_batch_limits_and_leaves_the_real_ledgers_alone(
        script, waits, tmp_path, monkeypatch):
    live_ledger = tmp_path / "batch-ledger.jsonl"
    monkeypatch.setattr(script, "LEDGER", live_ledger)
    assert script.main(["--out", str(tmp_path)]) == 0
    spend = report(tmp_path)["spend_after"]
    assert (spend["requests"], spend["max_requests"], spend["max_usd"]) == (10, 10, "0.01")
    assert not live_ledger.exists()


def test_a_batch_that_already_spent_a_call_cannot_start_again(script, tmp_path, monkeypatch,
                                                               capsys):
    ledger_path = tmp_path / "batch-ledger.jsonl"
    SpendLedger(ledger_path, max_requests=10, max_usd=Decimal("0.01")).reserve(
        "earlier", Decimal("0.00045"))
    before = ledger_path.read_bytes()
    monkeypatch.setattr(script, "LEDGER", ledger_path)
    assert script.main(["--live", "--yes", "--key", str(tmp_path / "absent.key"),
                        "--out", str(tmp_path / "out")]) == 2
    assert ledger_path.read_bytes() == before
    assert "budget" in capsys.readouterr().err.lower()
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("value", ["0", "29.9"])
def test_live_pacing_under_30_seconds_is_refused_before_ledger_or_credential_access(
        script, tmp_path, monkeypatch, capsys, value):
    def forbidden(*args, **kwargs):
        raise AssertionError("Short live pacing reached ledger or credential access")

    monkeypatch.setattr(script, "SpendLedger", forbidden)
    monkeypatch.setattr(script, "load_credential", forbidden)
    assert script.main(["--live", "--yes", f"--pace={value}",
                        "--out", str(tmp_path / "out")]) == 2
    assert "at least 30" in capsys.readouterr().err
