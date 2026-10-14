"""Owner-run, read-only live access check for the four platform connectors.

For each platform it reads one general and one restricted item as test users A and B with
their own credentials. Expected: A reads both; B reads the general item and is refused the
restricted one. Results record allowed/denied and an error category only: no document text,
no tokens and no email addresses are written or printed.

Usage (from the repository root):

    python eval/live_access/check.py discover --targets var/live-access/targets.json
    python eval/live_access/check.py check --targets var/live-access/targets.json

Tokens are read from ``--tokens`` (default ``~/.config/seaglass/live-access-tokens.json``),
which must be outside the repository and readable only by its owner (mode 0600).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aspire_brain.platforms.connectors import (  # noqa: E402
    ConnectorError,
    ConnectorSession,
    IdentityBinding,
    SourceRef,
    connector_for,
)
from aspire_brain.platforms.connectors.core import SourceUnavailable  # noqa: E402

PLATFORMS = ("confluence", "jira", "slack", "drive")
USERS = ("A", "B")
EXPECTED = {("A", "general"): "allowed", ("A", "restricted"): "allowed",
            ("B", "general"): "allowed", ("B", "restricted"): "denied"}
BASE_URLS = {"slack": "https://slack.com", "drive": "https://www.googleapis.com"}
TOKEN_KEYS = {"confluence": "atlassian", "jira": "atlassian", "slack": "slack", "drive": "drive"}
ACCOUNT_KEYS = {"confluence": "atlassian_account_id", "jira": "atlassian_account_id",
                "slack": "slack_user_id", "drive": "drive_permission_id"}
DEFAULT_TOKENS = Path("~/.config/seaglass/live-access-tokens.json").expanduser()
DEFAULT_OUT = ROOT / "var" / "live-access"


class SetupError(Exception):
    pass


def load_tokens(path: Path) -> dict:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise SetupError(f"Token file not found: {path}")
    if path.is_relative_to(ROOT):
        raise SetupError("Token file must be outside the repository")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise SetupError(f"Token file must be readable only by you: chmod 600 {path}")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise SetupError("Token file must be a JSON object keyed by user (A, B)")
    return data


def load_targets(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    for key in ("users", "items"):
        if not isinstance(data.get(key), dict):
            raise SetupError(f"Targets file needs a '{key}' object")
    return data


def _filled(value) -> bool:
    return isinstance(value, str) and bool(value) and not value.startswith("FILL")


def _site(platform, targets):
    """Jira may live on its own Atlassian site; it defaults to the shared ``atlassian_site``."""
    if platform == "jira" and _filled(targets.get("jira_site")):
        return targets["jira_site"]
    return targets.get("atlassian_site") if platform in {"confluence", "jira"} else BASE_URLS[platform]


def _session(platform, targets, user, token, *, account_id, transport=None):
    profile = targets["users"].get(user, {})
    base_url = _site(platform, targets)
    workspace = targets.get("slack_workspace_id", "") if platform == "slack" else ""
    binding = IdentityBinding(tenant_id="seaglass-live-check", principal_id=f"user-{user.lower()}",
                              account_id=account_id, workspace_id=workspace)
    auth_user = profile.get("atlassian_email") if platform in {"confluence", "jira"} else None
    return ConnectorSession(platform=platform, base_url=base_url, binding=binding, credential=token,
                            auth_user=auth_user, transport=transport, allow_live=transport is None)


def _missing(platform, targets, tokens, user, *, need_account=True):
    profile = targets["users"].get(user, {})
    token = tokens.get(user, {}).get(TOKEN_KEYS[platform])
    gaps = []
    if not _filled(token):
        gaps.append(f"token {user}.{TOKEN_KEYS[platform]}")
    if platform in {"confluence", "jira"}:
        if not _filled(_site(platform, targets)):
            gaps.append("atlassian_site")
        if not _filled(profile.get("atlassian_email")):
            gaps.append(f"users.{user}.atlassian_email")
    if platform == "slack" and need_account and not _filled(targets.get("slack_workspace_id")):
        gaps.append("slack_workspace_id")
    if need_account and not _filled(profile.get(ACCOUNT_KEYS[platform])):
        gaps.append(f"users.{user}.{ACCOUNT_KEYS[platform]}")
    return token, gaps


def discover(targets, tokens, platforms=PLATFORMS, transport=None) -> list[dict]:
    """Look up each user's own account identifiers; no resource is read."""
    rows = []
    for platform in platforms:
        for user in USERS:
            token, gaps = _missing(platform, targets, tokens, user, need_account=False)
            if gaps:
                rows.append({"platform": platform, "user": user, "result": "not_configured",
                             "missing": gaps})
                continue
            row = {"platform": platform, "user": user}
            try:
                with _session(platform, targets, user, token, account_id="discover",
                              transport=transport) as session:
                    if platform == "slack":
                        data = session.post_json("/api/auth.test")
                        if data.get("ok") is not True:
                            raise ConnectorError("expired_access")
                        if data.get("bot_id"):
                            raise ConnectorError("identity_mismatch")
                        row |= {"slack_user_id": data.get("user_id"),
                                "slack_workspace_id": data.get("team_id")}
                    elif platform == "drive":
                        data = session.get_json("/drive/v3/about", params={"fields": "user(permissionId)"})
                        row["drive_permission_id"] = data["user"]["permissionId"]
                    else:
                        path = "/rest/api/3/myself" if platform == "jira" else "/wiki/rest/api/user/current"
                        row["atlassian_account_id"] = session.get_json(path)["accountId"]
                row["result"] = "ok"
            except ConnectorError as exc:
                row |= {"result": "error", "error": exc.code}
            except (KeyError, TypeError):
                row |= {"result": "error", "error": "invalid_response"}
            rows.append(row)
    return rows


def _read(platform, targets, user, token, item, transport):
    profile = targets["users"][user]
    parent = targets.get("slack_workspace_id") if platform == "slack" else item.get("parent")
    with _session(platform, targets, user, token, account_id=profile[ACCOUNT_KEYS[platform]],
                  transport=transport) as session:
        documents = connector_for(session).fetch(SourceRef(platform, item["id"], parent))
    digest = hashlib.sha256("\n".join(d.content_sha256 for d in documents).encode()).hexdigest()
    return {"observed": "allowed", "documents": len(documents), "content_sha256": digest}


def check(targets, tokens, platforms=PLATFORMS, transport=None) -> list[dict]:
    rows = []
    for platform in platforms:
        items = targets["items"].get(platform, {})
        for user in USERS:
            token, gaps = _missing(platform, targets, tokens, user)
            for kind in ("general", "restricted"):
                item = items.get(kind, {})
                row = {"platform": platform, "user": user, "item": kind,
                       "label": item.get("label", ""), "expected": EXPECTED[(user, kind)],
                       "checked_at": datetime.now(UTC).isoformat(timespec="seconds")}
                item_gaps = gaps + [f"items.{platform}.{kind}.{key}" for key in ("id", "parent")
                                    if not (key == "parent" and platform == "slack")
                                    and not _filled(item.get(key))]
                if item_gaps:
                    rows.append(row | {"observed": "not_configured", "missing": item_gaps,
                                       "pass": False})
                    continue
                try:
                    row |= _read(platform, targets, user, token, item, transport)
                except SourceUnavailable:
                    row["observed"] = "denied"
                except ConnectorError as exc:
                    row |= {"observed": "error", "error": exc.code}
                row["pass"] = row["observed"] == row["expected"]
                rows.append(row)
    return rows


def _print_table(rows, columns):
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    for row in rows:
        print("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("discover", "check"))
    parser.add_argument("--targets", type=Path, default=DEFAULT_OUT / "targets.json")
    parser.add_argument("--tokens", type=Path, default=DEFAULT_TOKENS)
    parser.add_argument("--platform", choices=PLATFORMS, action="append",
                        help="limit to one platform (repeatable)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    platforms = tuple(args.platform or PLATFORMS)
    try:
        tokens, targets = load_tokens(args.tokens), load_targets(args.targets)
    except (SetupError, OSError, ValueError) as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return 2

    if args.command == "discover":
        rows = discover(targets, tokens, platforms)
        _print_table(rows, ["platform", "user", "result", "error", "atlassian_account_id",
                            "slack_user_id", "slack_workspace_id", "drive_permission_id"])
        for row in rows:
            if row.get("missing"):
                print(f"{row['platform']} {row['user']} missing: {', '.join(row['missing'])}")
        print("\nCopy these IDs into the targets file; they are identifiers, not secrets.")
        return 0 if all(r["result"] == "ok" for r in rows) else 1

    rows = check(targets, tokens, platforms)
    _print_table(rows, ["platform", "user", "item", "expected", "observed", "error", "pass",
                        "checked_at"])
    for row in rows:
        if row.get("missing"):
            print(f"{row['platform']} {row['user']} {row['item']} missing: {', '.join(row['missing'])}")
    passed = all(r["pass"] for r in rows)
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    result = {"result": "pass" if passed else "fail", "mode": "live", "platforms": list(platforms),
              "expectation": "A reads both items; B reads general and is refused restricted",
              "stores": "allowed/denied, error category, document count and content hash only",
              "rows": rows}
    out = args.out / f"results-{stamp}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"\n{'PASS' if passed else 'FAIL'}: {sum(r['pass'] for r in rows)}/{len(rows)} checks; "
          f"saved {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
