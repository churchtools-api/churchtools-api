"""Removes credentials from recorded responses before they are stored.

Used by `conftest.record`; run as a script to clean the existing fixtures:

    python tests/live/redact.py
"""

from __future__ import annotations

import json
import re
import sys
import typing as _t
from pathlib import Path

REDACTED = "<redacted>"

# Responses that are credentials as a whole; all their strings are replaced.
SECRET_OPERATIONS = {"get-persons-id-logintoken", "get-persons-id-loginstring"}

# Keys whose string values are credentials, e.g. `clientSecret`, `token`, `mail_smtp_args_password`.
SECRET_KEY = re.compile(r"secret|token|passw(or)?d|api_?key|loginstring|private_?key", re.IGNORECASE)

# Credentials in URLs inside strings, e.g. `...&key=AIza...`.
SECRET_QUERY = re.compile(r"([?&](?:key|token|secret|signature|api_?key|access_token)=)[^&\s\"'<>]+", re.IGNORECASE)


def _all_strings(value: _t.Any) -> _t.Any:
    if isinstance(value, str):
        return REDACTED
    if isinstance(value, dict):
        return {k: _all_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_all_strings(v) for v in value]
    return value


# Secrets found so far; they are also replaced where they appear inside other
# strings, e.g. in `iCalUrl` or a download URL of another response.
_known: _t.Set[str] = set()


def _is_secret(key: str, value: _t.Any) -> bool:
    return isinstance(value, str) and bool(value) and bool(SECRET_KEY.search(key))


def _collect(value: _t.Any, key: str = "") -> None:
    if isinstance(value, dict):
        attribute = value.get("attribute")
        named = isinstance(attribute, str) and bool(SECRET_KEY.search(attribute))
        for k, v in value.items():
            _collect(v, "secret" if named and k == "value" else k)
    elif isinstance(value, list):
        for v in value:
            _collect(v, key)
    elif _is_secret(key, value) and len(value) >= 6 and value != REDACTED and set(value) != {"*"}:
        _known.add(value)


def _replace(value: _t.Any, key: str = "") -> _t.Any:
    if isinstance(value, dict):
        # Settings come as {"attribute": "rosterICalSecret", "value": "..."}.
        attribute = value.get("attribute")
        named = isinstance(attribute, str) and bool(SECRET_KEY.search(attribute))
        return {k: _replace(v, "secret" if named and k == "value" else k) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace(v, key) for v in value]
    if isinstance(value, str):
        if _is_secret(key, value):
            return REDACTED
        for secret in _known:
            value = value.replace(secret, REDACTED)
        return SECRET_QUERY.sub(rf"\1{REDACTED}", value)
    return value


def scrub(value: _t.Any) -> _t.Any:
    """Replaces string values of secret-looking keys and credentials in URLs."""
    _collect(value)
    return _replace(value)


def redact(op_id: str, body: _t.Any) -> _t.Any:
    return _all_strings(body) if op_id in SECRET_OPERATIONS else scrub(body)


def main() -> int:
    recorded = Path(__file__).resolve().parents[3] / "fixtures" / "recorded"
    fixtures = sorted(recorded.glob("*.json"))
    for path in fixtures:  # first collect all secrets, so cross-references are found
        _collect(json.loads(path.read_text()))
    changed = 0
    for path in fixtures:
        fixture = json.loads(path.read_text())
        cleaned = {
            **fixture,
            "request": scrub(fixture.get("request")),
            "body": redact(fixture["operation"], fixture.get("body")),
        }
        if cleaned != fixture:
            path.write_text(json.dumps(cleaned, indent=1, ensure_ascii=False) + "\n")
            changed += 1
            print(f"redacted {path.name}")
    print(f"{changed} fixture(s) changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
