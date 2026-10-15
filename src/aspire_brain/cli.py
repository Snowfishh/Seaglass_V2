"""Explicit local operator commands. No network calls or destructive resets."""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from aspire_brain.audit import AuditError, AuditWriter, ProtectedAuditStore
from aspire_brain.audit.retention import RetentionPolicy
from aspire_brain.auth import AuthService
from aspire_brain.config import ConfigurationError, Settings, initialize_config
from aspire_brain.db import Database
from aspire_brain.evaluation import evaluate, evaluate_grounding
from aspire_brain.providers import ExternalProviderUnavailable, configured_provider


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=Path.cwd(), help="Local configuration/project root")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-demo")
    init.add_argument("--fixtures", type=Path)
    commands.add_parser("doctor")
    run = commands.add_parser("evaluate")
    run.add_argument("--offline", action="store_true", required=True)
    run.add_argument("--cases", type=Path)
    run.add_argument("--fixtures", type=Path)
    grounding = commands.add_parser("evaluate-grounding")
    grounding.add_argument("--offline", action="store_true", required=True)
    checkpoint = commands.add_parser("audit-checkpoint")
    checkpoint.add_argument("--tenant", required=True)
    checkpoint.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("audit-verify")
    verify.add_argument("--tenant", required=True)
    verify.add_argument("--checkpoint", type=Path)
    retention = commands.add_parser("apply-retention")
    retention.add_argument("--tenant", required=True)
    retention.add_argument("--apply", action="store_true",
                           help="Remove expired payloads; without it this is a rehearsal")
    revoke = commands.add_parser("revoke-source")
    revoke.add_argument("--version", required=True)
    ingest = commands.add_parser("import-fixtures")
    ingest.add_argument("--fixtures", type=Path, required=True)
    return result


def _runtime(settings):
    db = Database(settings.db_path)
    db.initialize()
    audit = AuditWriter(settings.db_path, settings.audit_key, witness=settings.audit_witness())
    audit.initialize()
    return db, audit


def _fixtures(args):
    if args.fixtures:
        return args.fixtures.resolve()
    root_fixture = args.root / "data/demo"
    if root_fixture.is_dir():
        return root_fixture
    return Path(__file__).resolve().parents[2] / "data/demo"


def _doctor(settings):
    if not settings.db_path.is_file():
        raise ConfigurationError("Database missing; run init-demo")
    db, _audit = _runtime(settings)
    configured_provider(settings.provider_mode, runtime=settings.provider_runtime,
                        credential=settings.provider_credential(),
                        ledger_path=settings.provider_ledger_path)
    with closing(db.connect()) as connection:
        compatible = connection.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()[0]
    writable = os.access(settings.db_path, os.W_OK) and os.access(settings.db_path.parent, os.W_OK)
    runtime = settings.provider_runtime
    result = {"schema_version": compatible, "fts5": db.fts_available,
              "retrieval_mode": "fts5_lexical" if db.fts_available else "authorized_lexical_fallback",
              "writable_paths": writable, "provider_mode": settings.provider_mode,
              "live_provider": ("configured" if runtime and runtime.is_entitled()
                                else "not_run"),
              "audit_retention": {"max_age_days": settings.audit_retention_days,
                                  "max_entries": settings.audit_retention_max_entries},
              "demo_mode": settings.demo_mode, "production_identity_provider": "absent"}
    if not writable:
        raise ConfigurationError("Database paths are not writable")
    return result


def execute(args):
    args.root = args.root.resolve()
    if args.command == "init-demo":
        settings = initialize_config(args.root)
        db, audit = _runtime(settings)
        fixtures = _fixtures(args)
        db.seed(fixtures / "manifest.json", fixtures / "principals.json", audit=audit)
        audit.anchor_all()
        return {"status": "initialized", "corpus": "fictional", "provider_mode": settings.provider_mode}
    settings = Settings.load(args.root)
    if args.command == "doctor":
        return _doctor(settings)
    if args.command == "evaluate":
        return evaluate(args.root, _fixtures(args), args.cases or args.root / "eval/cases.jsonl", settings.audit_key)
    if args.command == "evaluate-grounding":
        return evaluate_grounding(args.root, settings.audit_key)
    db, audit = _runtime(settings)
    if args.command == "apply-retention":
        if settings.payload_key is None:
            raise ConfigurationError("Run init-demo to create the protected audit payload key")
        protected = ProtectedAuditStore(
            settings.db_path, settings.payload_key, audit, AuthService(db),
            retention=RetentionPolicy(max_age_days=settings.audit_retention_days,
                                      max_entries=settings.audit_retention_max_entries))
        protected.initialize()
        return protected.apply_retention(tenant_id=args.tenant, now=datetime.now(UTC),
                                         apply=args.apply)
    if args.command == "import-fixtures":
        db.seed(args.fixtures / "manifest.json", args.fixtures / "principals.json", audit=audit)
        audit.anchor_all()
        return {"status": "imported"}
    if args.command == "revoke-source":
        db.revoke(args.version, audit)
        audit.anchor_all()
        return {"status": "revoked"}
    if args.command == "audit-checkpoint":
        checkpoint = audit.checkpoint(args.tenant)
        target = args.output if args.output.is_absolute() else args.root / args.output
        target.parent.mkdir(parents=True, exist_ok=True)
        # Never silently overwrite a previously retained trust anchor.
        with target.open("x") as stream:
            json.dump(checkpoint, stream, indent=2)
            stream.write("\n")
        return checkpoint
    checkpoint = json.loads(args.checkpoint.read_text()) if args.checkpoint else None
    return audit.verify(args.tenant, checkpoint)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        print(json.dumps(result, indent=2))
        return int(bool(result.get("failed", 0) > 0 or result.get("chain_valid") is False
                   or result.get("unsupported_claims", 0) > 0
                   or (args.command == "audit-verify" and args.checkpoint
                       and not result.get("verified_through_checkpoint"))))
    except (ConfigurationError, ExternalProviderUnavailable) as exc:
        print(json.dumps({"error": str(exc)}))
    except (ValueError, OSError, sqlite3.Error, AuditError):
        print(json.dumps({"error": "Local operation failed; verify configuration, metadata and output paths"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
