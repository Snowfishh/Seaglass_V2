"""Local configuration; generated secrets remain outside SQLite and source control."""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    db_path: Path
    session_secret: str
    audit_key: bytes
    demo_mode: bool = True
    provider_mode: str = "offline_extractive"

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
        if secrets.compare_digest(session, audit):
            raise ConfigurationError("Session and audit keys must be separate")
        return cls(
            db_path=local_path("ASPIRE_DB_PATH", "var/aspire.db"),
            session_secret=session.decode("ascii"), audit_key=audit,
            demo_mode=str(values.get("ASPIRE_DEMO_MODE", "false")).lower() == "true",
            provider_mode=values.get("ASPIRE_PROVIDER_MODE") or "offline_extractive",
        )


def initialize_config(root: Path):
    root = root.resolve()
    (root / "var").mkdir(mode=0o700, parents=True, exist_ok=True)
    default = (
        "ASPIRE_DEMO_MODE=true\nASPIRE_PROVIDER_MODE=offline_extractive\n"
        "ASPIRE_DB_PATH=var/aspire.db\nASPIRE_SESSION_KEY_PATH=var/session.key\n"
        "ASPIRE_AUDIT_KEY_PATH=var/audit.key\n"
    )
    _create_private(root / ".env", default)
    values = {**dotenv_values(root / ".env"), **os.environ}
    for name, default in [("ASPIRE_SESSION_KEY_PATH", "var/session.key"),
                          ("ASPIRE_AUDIT_KEY_PATH", "var/audit.key")]:
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
