import json
from pathlib import Path

from aspire_brain.cli import main
from aspire_brain.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_fresh_init_doctor_evaluate_and_checkpoint(tmp_path, capsys):
    prefix = ["--root", str(tmp_path)]
    assert main([*prefix, "init-demo", "--fixtures", str(ROOT / "data/demo")]) == 0
    settings = Settings.load(tmp_path)
    before = (tmp_path / "var/audit.key").read_bytes()
    assert main([*prefix, "init-demo", "--fixtures", str(ROOT / "data/demo")]) == 0
    assert before == (tmp_path / "var/audit.key").read_bytes()
    assert settings.session_secret.encode() != settings.audit_key
    assert settings.payload_key not in {settings.session_secret.encode(), settings.audit_key}
    assert main([*prefix, "doctor"]) == 0
    assert main([*prefix, "evaluate", "--offline", "--cases", str(ROOT / "eval/cases.jsonl")]) == 0
    report = json.loads((tmp_path / "artifacts/evaluation.json").read_text())
    assert report["failed"] == 0 and report["passed"] > 0
    checkpoint = tmp_path / "artifacts/audit-head.json"
    assert main([*prefix, "audit-verify", "--tenant", "demo-a"]) == 0
    assert main([*prefix, "audit-checkpoint", "--tenant", "demo-a", "--output", str(checkpoint)]) == 0
    assert main([*prefix, "audit-verify", "--tenant", "demo-a", "--checkpoint", str(checkpoint)]) == 0
    assert '"verified_through_checkpoint": true' in capsys.readouterr().out


def test_missing_configuration_and_invalid_provider_are_explicit(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "doctor"]) == 1
    assert "error" in capsys.readouterr().out.lower()


def test_grounding_evaluation_and_retention_commands(tmp_path, capsys):
    prefix = ["--root", str(tmp_path)]
    assert main([*prefix, "init-demo", "--fixtures", str(ROOT / "data/demo")]) == 0
    capsys.readouterr()
    assert main([*prefix, "evaluate-grounding", "--offline"]) == 0
    report = json.loads((tmp_path / "artifacts/g4-claim-support.json").read_text())
    assert report["mode"] == "simulated"
    assert report["unsupported_claims"] == 0
    assert report["unsupported_claim_control_detected"] is True
    assert report["provider_runtime"]["outcome"] == "not_run"
    assert report["live_model_claim_support"] is None
    capsys.readouterr()
    # Retention defaults to a rehearsal: nothing is removed without --apply.
    assert main([*prefix, "apply-retention", "--tenant", "demo-a"]) == 0
    rehearsal = json.loads(capsys.readouterr().out)
    assert rehearsal["applied"] is False and rehearsal["removed"] == 0
    assert rehearsal["policy"]["max_age_days"] == 90
    assert main([*prefix, "apply-retention", "--tenant", "demo-a", "--apply"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["applied"] is True and applied["chain_preserved"] is True
    assert main([*prefix, "doctor"]) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["provider_mode"] == "offline_extractive"
    assert doctor["live_provider"] == "not_run"
    assert doctor["audit_retention"] == {"max_age_days": 90, "max_entries": 10000}


def test_live_provider_mode_is_refused_without_enablement_and_entitlement(tmp_path, capsys):
    prefix = ["--root", str(tmp_path)]
    assert main([*prefix, "init-demo", "--fixtures", str(ROOT / "data/demo")]) == 0
    env = tmp_path / ".env"
    env.write_text(env.read_text().replace("ASPIRE_PROVIDER_MODE=offline_extractive\n",
                                           "ASPIRE_PROVIDER_MODE=live_grounded\n"))
    capsys.readouterr()
    assert main([*prefix, "doctor"]) == 1
    assert "explicit runtime configuration" in capsys.readouterr().out.lower()
    env.write_text(env.read_text() + "ASPIRE_PROVIDER_SERVICE=example\n"
                                      "ASPIRE_PROVIDER_MODEL=example-model\n"
                                      "ASPIRE_PROVIDER_ENDPOINT=https://api.example.invalid/v1\n"
                                      "ASPIRE_PROVIDER_REGION=ap-southeast-1\n"
                                      "ASPIRE_PROVIDER_ENABLED=true\n"
                                      "ASPIRE_PROVIDER_ENTITLEMENT=entitled\n")
    capsys.readouterr()
    # Entitlement alone does not enable a runtime this checkout does not implement.
    assert main([*prefix, "doctor"]) == 1
    assert "no request was made" in capsys.readouterr().out.lower()
