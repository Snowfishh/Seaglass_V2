"""Local configuration; generated secrets remain outside SQLite and source control."""

import os
import secrets
from dataclasses import dataclass
from decimal import Decimal
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
    #: Private provider key file, outside the project directory. Read only for a live mode.
    provider_key_path: Path | None = None
    #: Durable spend ledger shared by every process using a live provider.
    provider_ledger_path: Path | None = None
    root: Path | None = None

    def provider_credential(self) -> str | None:
        """The live provider key, or ``None`` when no live mode or key path is configured."""
        from aspire_brain.providers import LIVE_PROVIDER_MODES
        from aspire_brain.providers.live import load_credential

        if self.provider_mode not in LIVE_PROVIDER_MODES or self.provider_key_path is None:
            return None
        return load_credential(self.provider_key_path, project_root=self.root or Path.cwd())

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
            provider_key_path=(Path(values["ASPIRE_PROVIDER_KEY_PATH"]).expanduser()
                               if values.get("ASPIRE_PROVIDER_KEY_PATH") else None),
            provider_ledger_path=local_path("ASPIRE_PROVIDER_LEDGER_PATH",
                                            "var/provider/live-ledger.jsonl"),
            root=root,
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


#: Round-trip names for the generic provider runtime settings only. Campaign rounds, strategy
#: lists, rubrics, thresholds and approvals deliberately have no name here: they belong to the
#: eval-only red-team configuration and must never be loaded by the production service.
_PROVIDER_RUNTIME_FIELDS = (
    ("ASPIRE_PROVIDER_SERVICE", "service"),
    ("ASPIRE_PROVIDER_MODEL", "model"),
    ("ASPIRE_PROVIDER_ENDPOINT", "endpoint"),
    ("ASPIRE_PROVIDER_REGION", "region"),
    ("ASPIRE_PROVIDER_REGION_PROVENANCE", "region_provenance"),
    ("ASPIRE_PROVIDER_ENABLED", "enabled"),
    ("ASPIRE_PROVIDER_ENTITLEMENT", "entitlement"),
    ("ASPIRE_PROVIDER_MAX_COST_USD", "max_cost_usd"),
    ("ASPIRE_PROVIDER_TIMEOUT_SECONDS", "timeout_seconds"),
    ("ASPIRE_PROVIDER_REQUEST_CAP", "request_cap"),
    ("ASPIRE_PROVIDER_INPUT_TOKEN_CAP", "input_token_cap"),
    ("ASPIRE_PROVIDER_OUTPUT_TOKEN_CAP", "output_token_cap"),
    ("ASPIRE_PROVIDER_REASONING_TOKEN_CAP", "reasoning_token_cap"),
    ("ASPIRE_PROVIDER_TOTAL_TOKEN_CAP", "total_token_cap"),
    ("ASPIRE_PROVIDER_REASONING_EFFORT", "reasoning_effort"),
)


def provider_runtime_values(config: ProviderRuntimeConfig) -> dict[str, str]:
    """Serialise exactly the supplied configuration as strings.

    Reads nothing from the environment or ``.env``; unset (``None``) fields are omitted so a
    round trip cannot invent a value that was never configured.
    """
    values = {}
    for name, attribute in _PROVIDER_RUNTIME_FIELDS:
        value = getattr(config, attribute)
        if value is None:
            continue
        values[name] = "true" if value is True else "false" if value is False else str(value)
    return values


def _provider_text(values, name):
    raw = values.get(name)
    return None if raw is None or str(raw).strip() == "" else str(raw).strip()


def _provider_flag(values, name):
    raw = values.get(name)
    if raw is None or str(raw).strip() == "":
        return False
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text not in {"true", "false"}:
        raise ConfigurationError(f"{name} must be true or false")
    return text == "true"


def _provider_cap(values, name):
    """Accept only a plain non-negative integer; floats, booleans and '1.0' fail closed."""
    raw = values.get(name)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, bool) or not (isinstance(raw, int)
                                     or (isinstance(raw, str) and raw.strip().isdigit())):
        raise ConfigurationError(f"{name} must be a plain non-negative integer")
    return raw if isinstance(raw, int) else int(raw.strip())


def _provider_cost(values, name):
    raw = values.get(name)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Decimal("0")
    return raw


def _provider_runtime(values):
    """Build the generic runtime config only when a service is declared; disabled by default."""
    service = _provider_text(values, "ASPIRE_PROVIDER_SERVICE")
    if not service:
        return None
    return ProviderRuntimeConfig(
        service=service,
        model=_provider_text(values, "ASPIRE_PROVIDER_MODEL") or "unset",
        endpoint=_provider_text(values, "ASPIRE_PROVIDER_ENDPOINT") or "https://unset.invalid",
        region=_provider_text(values, "ASPIRE_PROVIDER_REGION"),
        region_provenance=_provider_text(values, "ASPIRE_PROVIDER_REGION_PROVENANCE"),
        enabled=_provider_flag(values, "ASPIRE_PROVIDER_ENABLED"),
        entitlement=_provider_text(values, "ASPIRE_PROVIDER_ENTITLEMENT") or "unknown",
        max_cost_usd=_provider_cost(values, "ASPIRE_PROVIDER_MAX_COST_USD"),
        timeout_seconds=values.get("ASPIRE_PROVIDER_TIMEOUT_SECONDS"),
        request_cap=_provider_cap(values, "ASPIRE_PROVIDER_REQUEST_CAP"),
        input_token_cap=_provider_cap(values, "ASPIRE_PROVIDER_INPUT_TOKEN_CAP"),
        output_token_cap=_provider_cap(values, "ASPIRE_PROVIDER_OUTPUT_TOKEN_CAP"),
        reasoning_token_cap=_provider_cap(values, "ASPIRE_PROVIDER_REASONING_TOKEN_CAP"),
        total_token_cap=_provider_cap(values, "ASPIRE_PROVIDER_TOTAL_TOKEN_CAP"),
        reasoning_effort=_provider_text(values, "ASPIRE_PROVIDER_REASONING_EFFORT"),
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
