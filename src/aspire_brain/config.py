"""Local configuration; generated secrets remain outside SQLite and source control."""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from aspire_brain.providers.runtime import ProviderRuntimeConfig


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    db_path: Path
    session_secret: str
    audit_key: bytes
    demo_mode: bool = True
    provider_mode: str = "offline_extractive"
    payload_key: bytes | None = None
    #: Only used by a live provider mode; ``None`` means no live runtime is configured.
    provider_runtime: ProviderRuntimeConfig | None = None
    #: Declared retention for protected audit payloads.
    audit_retention_days: int = 90
    audit_retention_max_entries: int = 10000

    @classmethod
    def load(cls, root: Path | None = None):
        root = (root or Path.cwd()).resolve()
        values = {**dotenv_values(root / ".env"), **os.environ}

        def local_path(name, default):
            path = Path(values.get(name) or default)
            return path if path.is_absolute() else root / path

        def read_secret(name, default):
            path = local_path(name, default)
            try:
                if os.name != "nt" and path.stat().st_mode & 0o077:
                    raise ConfigurationError("Secret file permissions must be 0600")
                secret = path.read_bytes().strip()
                if len(secret) < 32:
                    raise ConfigurationError("Secret file is invalid")
                return secret
            except OSError as exc:
                raise ConfigurationError("Run init-demo to create local configuration") from exc

        session = read_secret("ASPIRE_SESSION_KEY_PATH", "var/session.key")
        audit = read_secret("ASPIRE_AUDIT_KEY_PATH", "var/audit.key")
        payload = read_secret("ASPIRE_PAYLOAD_KEY_PATH", "var/payload.key")
        if (secrets.compare_digest(session, audit) or
            secrets.compare_digest(session, payload) or
            secrets.compare_digest(audit, payload)):
            raise ConfigurationError("Session, audit and payload keys must be separate")
        return cls(
            db_path=local_path("ASPIRE_DB_PATH", "var/aspire.db"),
            session_secret=session.decode("ascii"), audit_key=audit,
            demo_mode=str(values.get("ASPIRE_DEMO_MODE", "false")).lower() == "true",
            provider_mode=values.get("ASPIRE_PROVIDER_MODE") or "offline_extractive",
            payload_key=payload,
            provider_runtime=_provider_runtime(values),
            audit_retention_days=_positive_int(values, "ASPIRE_AUDIT_RETENTION_DAYS", 90),
            audit_retention_max_entries=_positive_int(values, "ASPIRE_AUDIT_RETENTION_MAX_ENTRIES",
                                                      10000),
        )


def _positive_int(values, name, default):
    raw = values.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ConfigurationError(f"{name} must be a positive integer")
    return value


def _provider_runtime(values):
    """Build a live runtime config only when a service is declared; it stays disabled by default."""
    service = (values.get("ASPIRE_PROVIDER_SERVICE") or "").strip()
    if not service:
        return None
    return ProviderRuntimeConfig(
        service=service,
        model=(values.get("ASPIRE_PROVIDER_MODEL") or "unset").strip(),
        endpoint=(values.get("ASPIRE_PROVIDER_ENDPOINT") or "https://unset.invalid").strip(),
        region=(values.get("ASPIRE_PROVIDER_REGION") or "unset").strip(),
        enabled=str(values.get("ASPIRE_PROVIDER_ENABLED", "false")).lower() == "true",
        entitlement=(values.get("ASPIRE_PROVIDER_ENTITLEMENT") or "unknown").strip(),
    )


def initialize_config(root: Path):
    root = root.resolve()
    (root / "var").mkdir(mode=0o700, parents=True, exist_ok=True)
    default = (
        "ASPIRE_DEMO_MODE=true\nASPIRE_PROVIDER_MODE=offline_extractive\n"
        "ASPIRE_DB_PATH=var/aspire.db\nASPIRE_SESSION_KEY_PATH=var/session.key\n"
        "ASPIRE_AUDIT_KEY_PATH=var/audit.key\n"
        "ASPIRE_PAYLOAD_KEY_PATH=var/payload.key\n"
        "# Declared retention for encrypted protected audit payloads.\n"
        "ASPIRE_AUDIT_RETENTION_DAYS=90\n"
        "ASPIRE_AUDIT_RETENTION_MAX_ENTRIES=10000\n"
        "# A live provider additionally needs ASPIRE_PROVIDER_SERVICE and explicit\n"
        "# enablement plus a confirmed entitlement; offline_extractive and\n"
        "# fake_grounded need neither.\n"
    )
    _create_private(root / ".env", default)
    values = {**dotenv_values(root / ".env"), **os.environ}
    for name, default in [("ASPIRE_SESSION_KEY_PATH", "var/session.key"),
                          ("ASPIRE_AUDIT_KEY_PATH", "var/audit.key"),
                          ("ASPIRE_PAYLOAD_KEY_PATH", "var/payload.key")]:
        path = Path(values.get(name) or default)
        path = path if path.is_absolute() else root / path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _create_private(path, secrets.token_hex(32) + "\n")
    return Settings.load(root)


def _create_private(path: Path, content: str):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "w") as stream:
        stream.write(content)
