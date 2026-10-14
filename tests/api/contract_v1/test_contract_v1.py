"""Contract v1 parity — the pydantic wire models against the frontend's own Zod (ARV2 D3).

Three checks, and they are deliberately three rather than one:

1. **Field parity.** For each of the five payloads, the pydantic model's *alias* set equals the
   Zod schema's ``required ∪ optional``, and the pydantic *required* set equals the Zod required
   set. A v1 field may not be silently optional on one side: a Zod ``.nullable()`` without a
   default is REQUIRED-but-nullable, so its pydantic twin is ``X | None`` with **no** default.
2. **Golden payloads.** A hand-built maximal and minimal sample per payload validates with
   pydantic and — when Node and ``apps/frontend``'s ``zod`` are present — parses through the real
   Zod schema. This is what catches the serialization rules the field sets cannot see: an absent
   optional must be *omitted* (a Zod ``.optional()`` that is not ``.nullable()`` rejects ``null``),
   while a required-nullable field must serialize as ``null``.
3. **Document parity.** The field tables under ``## Contract v1`` in
   ``apps/frontend/docs/api-contracts/accounts.md`` list exactly the fields on the wire.

The Zod half is skipped, naming the missing toolchain, when ``node`` or
``apps/frontend/node_modules`` is unavailable. See ``README.md`` for the exact incantation and
why ``NODE_PATH`` is how ``zod`` resolves.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from clue_api.frontend_read.contract_v1 import V1_PAYLOADS
from tests.api.contract_v1.oracle import require_node, run_validate, zod_validate

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_ZOD_FIELDS = _HERE / "zod-fields.json"
_VALIDATE_TS = _HERE / "validate.ts"
_ACCOUNTS_MD = _REPO_ROOT / "apps" / "frontend" / "docs" / "api-contracts" / "accounts.md"

#: The ``### E<n> — <title> (<ZodSchemaName>)`` subheadings the doc section must carry.
DOC_HEADING_RE = re.compile(r"^###\s+E\d+\s+—\s+.*\((?P<schema>\w+Schema)\)\s*$")
DOC_SECTION_HEADING = "## Contract v1 — the accounts screens (ARV2 D3, 2026-09-08)"


# --- the Node half's toolchain ----------------------------------------------------------------
#
# The probe and the runner live in ``oracle.py`` so this suite and the endpoint suites'
# ``?contract=v1`` halves validate through exactly the same call.


# --- helpers ----------------------------------------------------------------------------------


def _zod_fields() -> dict[str, dict[str, list[str]]]:
    return json.loads(_ZOD_FIELDS.read_text())


def _aliases(model: type[BaseModel]) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


def _required_aliases(model: type[BaseModel]) -> set[str]:
    return {
        field.alias or name for name, field in model.model_fields.items() if field.is_required()
    }


def _dump(payload: BaseModel) -> dict[str, Any]:
    return payload.model_dump(mode="json", by_alias=True, exclude_none=False)


# --- (1) field parity -------------------------------------------------------------------------


@pytest.mark.parametrize("schema_name", sorted(_zod_fields()))
def test_zod_and_pydantic_carry_the_same_fields(schema_name: str) -> None:
    zod = _zod_fields()[schema_name]
    model = V1_PAYLOADS[schema_name]
    assert _aliases(model) == set(zod["required"]) | set(zod["optional"])


@pytest.mark.parametrize("schema_name", sorted(_zod_fields()))
def test_required_on_one_side_is_required_on_the_other(schema_name: str) -> None:
    zod = _zod_fields()[schema_name]
    model = V1_PAYLOADS[schema_name]
    assert _required_aliases(model) == set(zod["required"])


def test_v1_payloads_names_the_five_zod_schemas() -> None:
    assert set(V1_PAYLOADS) == set(_zod_fields())


def test_committed_zod_fields_matches_the_live_schemas() -> None:
    """`zod-fields.json` is generated; regenerate it here so the two cannot drift silently."""
    root = require_node()
    result = run_validate(root, "--shapes")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == _zod_fields(), (
        "tests/api/contract_v1/zod-fields.json is stale — regenerate it (see README.md)"
    )


# --- (1b) allowed values -------------------------------------------------------------------------
#
# Review finding K1-1: the backend added `"site"` to an account artifact's types and the frontend's
# Zod list did not, so a single site artifact made the whole accounts read fail. The field-name
# parity above could not see it: it compares names, and only at the top level. This compares the
# allowed values of every fixed-list field, at any depth: whatever the backend may send there, the
# frontend must accept. (The frontend may accept more; a plain string is not a fixed list.)


def _fixed_values(node: dict[str, Any], defs: dict[str, Any]) -> list[Any] | None:
    node = _deref(node, defs)
    if "const" in node:
        return [node["const"]]
    if "enum" in node:
        return list(node["enum"])
    options = node.get("anyOf") or node.get("oneOf")
    if options:
        values: list[Any] = []
        for option in options:
            option = _deref(option, defs)
            if option.get("type") == "null":
                continue
            option_values = _fixed_values(option, defs)
            if option_values is None:
                return None
            values.extend(option_values)
        return values or None
    return None


def _deref(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        node = defs[node["$ref"].rsplit("/", 1)[-1]]
    return node


def _walk_enums(
    node: dict[str, Any],
    path: str,
    defs: dict[str, Any],
    out: dict[str, set[Any]],
    seen: frozenset[str],
) -> None:
    ref = node.get("$ref")
    if ref is not None:
        if ref in seen:
            return
        seen = seen | {ref}
    node = _deref(node, defs)
    values = _fixed_values(node, defs)
    if values is not None:
        out[path] = set(values)
        return
    for key, child in (node.get("properties") or {}).items():
        _walk_enums(child, f"{path}.{key}", defs, out, seen)
    if isinstance(node.get("items"), dict):
        _walk_enums(node["items"], f"{path}[]", defs, out, seen)
    for option in node.get("anyOf") or node.get("oneOf") or []:
        _walk_enums(option, path, defs, out, seen)


def _backend_enums() -> dict[str, set[Any]]:
    out: dict[str, set[Any]] = {}
    for name, model in V1_PAYLOADS.items():
        schema = model.model_json_schema(by_alias=True, mode="serialization")
        _walk_enums(schema, name, schema.get("$defs", {}), out, frozenset())
    return out


def _frontend_enums() -> dict[str, set[Any]]:
    root = require_node()
    result = run_validate(root, "--enums")
    assert result.returncode == 0, result.stderr
    return {path: set(values) for path, values in json.loads(result.stdout).items()}


def test_every_value_the_backend_may_send_is_one_the_frontend_accepts() -> None:
    frontend = _frontend_enums()
    backend = _backend_enums()
    # A guard on the guard: both walkers must reach a nested field, or this passes vacuously.
    nested = "AccountWorkspaceSchema.artifacts[].type"
    assert nested in frontend and nested in backend, (sorted(frontend), sorted(backend))
    refused = {
        path: sorted(values - frontend[path], key=str)
        for path, values in sorted(backend.items())
        if path in frontend and values - frontend[path]
    }
    assert refused == {}, f"the backend may send values the frontend refuses: {refused}"


# --- (2) golden payloads ----------------------------------------------------------------------


def _evidence(claim_id: str) -> dict[str, Any]:
    return {
        "claimId": claim_id,
        "sourceUrl": "https://example.com/post",
        "sourceDomain": "example.com",
        "faviconUrl": "https://example.com/favicon.ico",
        "title": "A source page",
        "quote": "the verbatim evidence span",
        "researchExcerpt": "the research sentence",
        "publishedAt": "2026-06-17",
        "verifiedAt": "2026-09-01",
        "verificationKind": "verified",
        "mediaTimestamp": "00:12:31",
        "provider": "exa",
        "outreachSafe": True,
    }


def _display_block(page: str) -> dict[str, Any]:
    return {
        "page": page,
        "sections": [
            {
                "key": "why-they-fit",
                "h1": "Why they fit",
                "empty": False,
                "items": [
                    {
                        "id": "item-1",
                        "h2": "They already run the stack",
                        "body": [
                            {
                                "text": "They run Snowflake.",
                                "claimIds": ["claim-1"],
                                "segments": [
                                    {"text": "They run Snowflake.", "claimIds": ["claim-1"]}
                                ],
                            }
                        ],
                        "sendLine": {
                            "channel": "email",
                            "text": "Opening line",
                            "claimIds": ["claim-1"],
                        },
                        "contactRefs": [
                            {
                                "accountId": "acct-1",
                                "contactId": "contact-1",
                                "name": "Nick Fisher",
                                "title": "VP Engineering",
                                "persona": "technical evaluator",
                                "emailState": "verified",
                                "avatarUrl": "/avatars/nick.png",
                            }
                        ],
                        "inlineLead": True,
                        "fitDisposition": "support",
                        "subject": {
                            "accountId": "acct-1",
                            "contactId": "contact-1",
                            "name": "Nick Fisher",
                        },
                        "priority": 1,
                        "newSinceLastVisit": False,
                    }
                ],
                "intro": [{"text": "An intro sentence.", "claimIds": []}],
                "restricted": False,
                "defaultOpen": False,
                "emptyMessage": "No information found.",
            }
        ],
    }


def _owner() -> dict[str, Any]:
    return {"id": "user-1", "name": "Aryan Keshri", "avatarUrl": "/avatars/aryan.png"}


def _account_max() -> dict[str, Any]:
    return {
        "id": "acct-1",
        "name": "Zafran",
        "logoPath": "/logos/zafran.png",
        "websiteUrl": "https://zafran.io",
        "researchStatus": "completed",
        "researchStatusLabel": "Fully researched",
        "researchIsRefreshing": False,
        "overallFit": "High",
        "fitScore": 87,
        "revenueBand": "$10M–$50M",
        "employeeBand": "51–200",
        "locationCount": 3,
        "locationsLabel": "Tel Aviv +2",
        "owner": _owner(),
        "createdBy": _owner(),
        "industryLabels": ["Cybersecurity"],
        "socials": [
            {"id": "s1", "label": "LinkedIn", "url": "https://linkedin.com/company/zafran"}
        ],
        "createdAt": "2026-06-01T09:00:00Z",
        "lastModifiedAt": "2026-09-01T09:00:00Z",
        "primaryProjectId": "proj-1",
        "projects": [{"id": "proj-1", "name": "Q4 ABM"}],
        "customFields": [
            {
                "id": "cf-1",
                "label": "Compliance regime",
                "value": "SOC 2",
                "presentation": "badge",
                "primary": True,
            }
        ],
    }


def _account_min() -> dict[str, Any]:
    return {
        "id": "acct-2",
        "name": "Probook",
        "logoPath": None,
        "websiteUrl": None,
        "researchStatus": "not_started",
        "overallFit": None,
        "fitScore": None,
        "revenueBand": "Unknown",
        "employeeBand": "Unknown",
        "locationCount": 0,
    }


def _account_detail_max() -> dict[str, Any]:
    return {
        "id": "acct-1",
        "name": "Zafran",
        "previewTitle": "Zafran",
        "logoPath": "/logos/zafran.png",
        "websiteUrl": "https://zafran.io",
        "websiteLabel": "zafran.io",
        "researchStatus": "completed",
        "researchStatusLabel": "Fully researched",
        "owner": _owner(),
        "createdBy": _owner(),
        "industryLabels": ["Cybersecurity"],
        "headcountLabel": "51–200 employees",
        "locationsLabel": "Tel Aviv +2",
        "revenueLabel": "$10M–$50M",
        "foundedLabel": "Founded 2022",
        "fundingLabel": "Series A",
        "fitScore": 87,
        "fitScoreLabel": "87 / 100",
        "createdAt": "2026-06-01T09:00:00Z",
        "lastModifiedAt": "2026-09-01T09:00:00Z",
        "socials": [
            {"id": "s1", "label": "LinkedIn", "url": "https://linkedin.com/company/zafran"}
        ],
        "customFields": [
            {
                "id": "cf-1",
                "label": "Compliance regime",
                "value": "SOC 2",
                "presentation": "text",
                "primary": False,
            }
        ],
        "overallFit": "High",
        "summaryParagraphs": ["They do X."],
        "businessParagraphs": ["They sell Y."],
        "fitCriteria": [
            {"id": "fc-1", "matched": True, "title": "Runs Snowflake", "evidence": "job req"}
        ],
        "contacts": [
            {
                "id": "contact-1",
                "name": "Nick Fisher",
                "avatarUrl": "/avatars/nick.png",
                "title": "VP Engineering",
                "persona": "technical evaluator",
                "emailVerified": True,
                "hasDetail": True,
            }
        ],
        "insights": [
            {
                "id": "ins-1",
                "source": "link",
                "title": "Funding round",
                "dateLabel": "17 June 2026",
                "url": "https://example.com/funding",
            }
        ],
        "activity": [
            {
                "id": "act-1",
                "kind": "summary",
                "text": "Research completed",
                "timeLabel": "2 days ago",
                "actor": {"type": "clue"},
                "action": "researched",
                "occurredAt": "2026-09-01T09:00:00Z",
                "isSample": False,
            },
            {
                "id": "act-2",
                "kind": "created",
                "text": "Account created",
                "timeLabel": "3 months ago",
                "actor": {
                    "type": "person",
                    "id": "user-1",
                    "name": "Aryan Keshri",
                    "avatarUrl": "/avatars/aryan.png",
                },
            },
        ],
        "headerMetadata": ["Cybersecurity", "Tel Aviv"],
        "researchEvidence": [_evidence("claim-1")],
        "overviewDisplay": _display_block("overview"),
        "buyingCommittee": [
            {
                "contactId": "contact-1",
                "name": "Nick Fisher",
                "title": "VP Engineering",
                "persona": "technical evaluator",
                "email": "nick@zafran.io",
                "emailClaimId": "claim-2",
                "linkedinUrl": "https://linkedin.com/in/nickfisher",
                "whyTheyMatter": "Owns the evaluation.",
            },
            {
                "contactId": "contact-2",
                "name": "Dana Levi",
                "title": "CFO",
                "persona": "economic buyer",
                "email": None,
                "emailClaimId": None,
                "linkedinUrl": None,
                "whyTheyMatter": "Signs the cheque.",
            },
        ],
    }


def _account_detail_min() -> dict[str, Any]:
    return {
        "id": "acct-2",
        "name": "Probook",
        "previewTitle": "Probook",
        "logoPath": None,
        "websiteUrl": None,
        "websiteLabel": "—",
        "researchStatus": "not_started",
        "headcountLabel": "Unknown",
        "locationsLabel": "Unknown",
        "revenueLabel": "Unknown",
        "fitScore": None,
        "createdAt": "2026-06-01T09:00:00Z",
        "lastModifiedAt": "2026-09-01T09:00:00Z",
        "overallFit": None,
        "fitCriteria": [],
        "contacts": [],
        "insights": [],
        "activity": [],
    }


def _account_workspace_max() -> dict[str, Any]:
    return {
        "accountId": "acct-1",
        "insights": [
            {
                "id": "wi-1",
                "source": "linkedin",
                "title": "Hiring for platform",
                "sourceLabel": "LinkedIn",
                "url": "https://linkedin.com/posts/1",
                "summary": "They are hiring.",
            }
        ],
        "insightSummary": ["7 insights", "4 people"],
        "researchEvidence": [_evidence("claim-1")],
        "insightsDisplay": _display_block("insights"),
        "artifacts": [
            {
                "id": "art-1",
                "title": "Landing page",
                "type": "web",
                "accountId": "acct-1",
                "projectName": "Q4 ABM",
                "updatedAt": "2026-09-01T09:00:00Z",
                "thumbnailPath": "/thumbs/art-1.png",
                "lastEditedLabel": "2 days ago",
            }
        ],
        "activity": [
            {
                "id": "act-1",
                "kind": "artifact",
                "text": "Landing page generated",
                "timeLabel": "2 days ago",
            }
        ],
    }


def _account_workspace_min() -> dict[str, Any]:
    return {"accountId": "acct-2", "insights": [], "artifacts": [], "activity": []}


def _contact_summary_max() -> dict[str, Any]:
    return {
        "id": "contact-1",
        "name": "Nick Fisher",
        "title": "VP Engineering",
        "persona": "technical evaluator",
        "personaTone": "blue",
        "influence": "High",
        "avatarUrl": "/avatars/nick.png",
        "emailStatus": "available",
        "emailLabel": "nick@zafran.io",
        "socials": ["linkedin", "x"],
        "profileAction": "page",
    }


def _contact_summary_min() -> dict[str, Any]:
    return {
        "id": "contact-2",
        "name": "Dana Levi",
        "title": None,
        "persona": "economic buyer",
        "personaTone": "olive",
        "influence": "Medium",
        "emailStatus": "lookup",
        "socials": [],
    }


def _contact_detail_max() -> dict[str, Any]:
    return {
        **_contact_summary_max(),
        "accountId": "acct-1",
        "accountName": "Zafran",
        "accountLogoPath": "/logos/zafran.png",
        "recentSignalsLabel": "3 recent signals",
        "linkedinLabel": "nickfisher",
        "linkedinUrl": "https://linkedin.com/in/nickfisher",
        "xLabel": "@nickfisher",
        "xUrl": "https://x.com/nickfisher",
        "emailVerifiedAt": "2026-09-01",
        "emailClaimId": "claim-2",
        "locationLabel": "Tel Aviv",
        "bestFirstChannelLabel": "LinkedIn DM",
        "educationLabel": "Technion",
        "tenureLabel": "3 years",
        "employmentStartedAt": "2023-04-01",
        "linkedinFollowers": 4200,
        "linkedinCreator": False,
        "locationClaimId": "claim-3",
        "reports": [
            {"accountId": "acct-1", "contactId": "contact-3", "name": "Ari Cohen"},
        ],
        "overviewParagraphs": ["He owns the platform team."],
        "evidence": [
            {
                "id": "ev-1",
                "source": "x",
                "title": "A post",
                "dateLabel": "17 June 2026",
                "url": "https://x.com/nickfisher/status/1",
            }
        ],
        "researchEvidence": [_evidence("claim-1")],
        "contactDisplay": _display_block("contact"),
        "lastModifiedAt": "2026-09-01T09:00:00Z",
    }


def _contact_detail_min() -> dict[str, Any]:
    return {
        **_contact_summary_min(),
        "accountId": "acct-2",
        "accountName": "Probook",
        "accountLogoPath": None,
        "recentSignalsLabel": "No recent signals",
        "linkedinLabel": "danalevi",
        "linkedinUrl": "https://linkedin.com/in/danalevi",
        "evidence": [],
        "lastModifiedAt": "2026-09-01T09:00:00Z",
    }


GOLDEN: dict[str, dict[str, dict[str, Any]]] = {
    "AccountSchema": {"max": _account_max(), "min": _account_min()},
    "AccountDetailSchema": {"max": _account_detail_max(), "min": _account_detail_min()},
    "AccountWorkspaceSchema": {
        "max": _account_workspace_max(),
        "min": _account_workspace_min(),
    },
    "AccountContactSummarySchema": {
        "max": _contact_summary_max(),
        "min": _contact_summary_min(),
    },
    "AccountContactDetailSchema": {
        "max": _contact_detail_max(),
        "min": _contact_detail_min(),
    },
}

_GOLDEN_CASES = [
    (schema_name, variant) for schema_name in sorted(GOLDEN) for variant in ("max", "min")
]


@pytest.mark.parametrize(("schema_name", "variant"), _GOLDEN_CASES)
def test_golden_payload_validates_with_pydantic(schema_name: str, variant: str) -> None:
    model = V1_PAYLOADS[schema_name]
    payload = model.model_validate(GOLDEN[schema_name][variant])
    dumped = _dump(payload)
    zod = _zod_fields()[schema_name]
    # Required-nullable fields serialize; absent optionals are omitted, never `null`.
    assert set(zod["required"]) <= set(dumped)
    assert set(dumped) <= set(zod["required"]) | set(zod["optional"])


#: The only *optional* (defaulted) top-level fields contract v1 serializes as ``null`` rather than
#: omitting: each one is ``.nullish()`` or ``.nullable().default(null)`` in the Zod, so ``null`` is
#: a value it accepts. Every other optional is ``.optional()`` without ``.nullable()`` — Zod
#: *rejects* ``null`` there, so an unknown value must be omitted from the JSON entirely.
NULL_SERIALIZING_OPTIONALS: dict[str, set[str]] = {
    "AccountSchema": {"owner", "createdBy", "primaryProjectId"},
    "AccountDetailSchema": {"owner", "createdBy"},
    "AccountWorkspaceSchema": set(),
    "AccountContactSummarySchema": {"membershipState"},
    "AccountContactDetailSchema": {"emailClaimId", "membershipState"},
}


@pytest.mark.parametrize(("schema_name", "variant"), _GOLDEN_CASES)
def test_an_unknown_optional_is_omitted_never_serialized_as_null(
    schema_name: str, variant: str
) -> None:
    """A Zod `.optional()` that is not `.nullable()` rejects `null` — so absent must mean absent."""
    model = V1_PAYLOADS[schema_name]
    dumped = _dump(model.model_validate(GOLDEN[schema_name][variant]))
    allowed = set(_zod_fields()[schema_name]["required"]) | NULL_SERIALIZING_OPTIONALS[schema_name]
    nulls = {alias for alias, value in dumped.items() if value is None}
    assert nulls <= allowed, (
        f"{schema_name} ({variant}) serialized {sorted(nulls - allowed)} as null; those fields "
        "are optional-not-nullable on the wire and must be omitted instead"
    )


@pytest.mark.parametrize(("schema_name", "variant"), _GOLDEN_CASES)
def test_golden_payload_parses_with_the_real_zod(schema_name: str, variant: str) -> None:
    model = V1_PAYLOADS[schema_name]
    zod_validate(_dump(model.model_validate(GOLDEN[schema_name][variant])), schema_name)


def test_the_zod_oracle_actually_rejects_a_bad_payload(tmp_path: Path) -> None:
    """A guard on the guard: `validate.ts` must fail a payload the contract forbids."""
    root = require_node()
    bad = dict(GOLDEN["AccountSchema"]["max"], fitScore=101)
    payload_file = tmp_path / "bad.json"
    payload_file.write_text(json.dumps(bad))
    result = run_validate(root, str(payload_file), "AccountSchema")
    assert result.returncode == 1, result.stdout


# --- (3) document parity ----------------------------------------------------------------------


def _doc_tables() -> dict[str, set[str]]:
    """The v1 section's per-payload field tables, keyed by the Zod schema in the subheading."""
    lines = _ACCOUNTS_MD.read_text().splitlines()
    try:
        start = lines.index(DOC_SECTION_HEADING)
    except ValueError:  # pragma: no cover - the assertion below reports it
        return {}
    tables: dict[str, set[str]] = {}
    schema: str | None = None
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        heading = DOC_HEADING_RE.match(line)
        if heading is not None:
            schema = heading.group("schema")
            tables.setdefault(schema, set())
            continue
        if schema is None or not line.startswith("| `"):
            continue
        field = line.split("|")[1].strip()
        if field.startswith("`") and field.endswith("`"):
            tables[schema].add(field.strip("`"))
    return tables


def test_the_doc_has_a_contract_v1_section() -> None:
    assert DOC_SECTION_HEADING in _ACCOUNTS_MD.read_text()


@pytest.mark.parametrize("schema_name", sorted(_zod_fields()))
def test_the_doc_lists_every_wire_field(schema_name: str) -> None:
    documented = _doc_tables()
    assert schema_name in documented, (
        f"accounts.md § Contract v1 has no `### E<n> — … ({schema_name})` field table"
    )
    assert documented[schema_name] == _aliases(V1_PAYLOADS[schema_name])
