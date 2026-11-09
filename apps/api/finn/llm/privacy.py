"""Privacy firewall (DECISIONS D-008).

Gemini free tier may use prompts to improve Google products. Therefore:
1. Every LLM call must declare an allowed `source_kind` ('public_filing', 'user_query_text', 'system_ping').
   Any other source_kind (e.g. 'network', 'contact', 'notes') raises PrivacyViolationError immediately.
2. Payloads are scanned against private tokens loaded from `data/seed/network/contacts.json`
   (contact IDs, synthetic contact emails, and private meeting notes), plus structural keys
   (`notes_enc`, `contact_id`, `__finn_private__`). If any match is found, the call is blocked
   before touching cache or network.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ALLOWED_SOURCE_KINDS = frozenset({"public_filing", "user_query_text", "system_ping"})
FORBIDDEN_KEYS = frozenset(
    {"notes", "notes_enc", "contact_links", "affiliations", "last_contacted", "__finn_private__"}
)


class PrivacyViolationError(RuntimeError):
    """Raised when private investor network data is passed toward an LLM boundary."""


@lru_cache(maxsize=1)
def _load_private_fingerprints(data_dir: str) -> tuple[str, ...]:
    path = Path(data_dir) / "seed" / "network" / "contacts.json"
    if not path.exists():
        return ()
    raw = json.loads(path.read_text())
    needles: list[str] = []
    for c in raw.get("contacts", []):
        if cid := c.get("id"):
            needles.append(str(cid))
        if email := c.get("email"):
            needles.append(str(email))
        # Any substring of a private meeting note (>= 24 chars) is fingerprinted
        note = (c.get("notes") or "").strip()
        if len(note) >= 24:
            needles.append(note[:32])
            needles.append(note)
    return tuple(needles)


def _walk_for_forbidden_keys(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in FORBIDDEN_KEYS:
                return f"forbidden key '{k}' in LLM payload"
            hit = _walk_for_forbidden_keys(v)
            if hit:
                return hit
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            hit = _walk_for_forbidden_keys(item)
            if hit:
                return hit
    return None


def assert_no_private_network_data(
    payload: Any,
    *,
    source_kind: str,
    data_dir: Path,
) -> None:
    if source_kind not in ALLOWED_SOURCE_KINDS:
        raise PrivacyViolationError(
            f"source_kind={source_kind!r} is not permitted for LLM calls; "
            f"allowed={sorted(ALLOWED_SOURCE_KINDS)}"
        )

    key_hit = _walk_for_forbidden_keys(payload)
    if key_hit:
        raise PrivacyViolationError(key_hit)

    serialized = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    if "[PRIVATE_NETWORK]" in serialized or "contact:" in serialized:
        raise PrivacyViolationError("Private contact identifier detected in LLM prompt")

    for needle in _load_private_fingerprints(str(data_dir)):
        if needle and needle in serialized:
            raise PrivacyViolationError(
                "Private investor network content (email/note/id) detected in LLM prompt"
            )
