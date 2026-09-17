"""The structuring client against the real model — Global Constraint 3: no replay, no mocks.

Three calls, one subject each, over the proof-of-concept's own bundles and its own field catalog,
so the numbers here are comparable with the numbers the PoC recorded: two accounts (Zafran from
the Exa deep report plus its own-site pages, Probook from its account report) and one person
(Nick Fisher). Roughly $0.10 a run, one to two minutes a call.

What is asserted is the contract, not the model's taste: every kept key is registered, every claim
carries a priority in 1–3, the verbatim rate clears its floor, and the ledger row carries
OpenRouter's own ``upstream_inference_cost``. The actual tallies are printed so a run can be
compared against the PoC rather than merely passing.
"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path

import pytest

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.structuring_client import (
    UNREGISTERED_KEY_ORIGIN,
    AccountSubject,
    FieldCatalog,
    FieldSpec,
    PersonSubject,
    StructuredOutput,
    StructuringClient,
)
from clue_config import Secrets, Settings
from clue_config.gateway import GatewayConfig
from tests.arv2.conftest import require_secret

REPO = Path(__file__).resolve().parents[2]
CONTEXT = REPO / ".context"

#: The PoC's catalog of REAL registered keys: 24 account, 8 contact, 12 facet.
CATALOG_SOURCE = CONTEXT / "arv2-smoke-cluehq" / "field_catalog.py"

#: The floor the EXACT verbatim rate must clear. The PoC measured 94% on this bundle; the floor is
#: set well below it so a normal model wobble is not a red test, while a collapse still is.
EXACT_VERBATIM_FLOOR = 0.5


#: Registered facet fields the proof-of-concept's ``field_catalog.py`` predates.
#:
#: ``p4_structure.py`` carried these three as ``PROPOSED_KEYS`` — real material with no registered
#: home at the time — and master plan §4 has since registered all three ("New registered fields
#: (data rows, no code): … contact — ``contact.facet.hooks``, ``.openers``, ``.voice_quote``
#: (``media_url`` + ``timestamp``)"). Without them the live person call structures against a
#: catalog the production lane does not have: the model reliably emits rows on exactly these keys,
#: they are re-filed to ``proposed`` as unregistered, and the kept-claim count moves run to run for
#: a reason that no longer exists in production. They declare no value schema, so ``schema_valid``
#: is ``None`` for them — "not checked", never a silent pass.
REGISTERED_SINCE_THE_POC: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="contact.facet.hooks",
        description="Grounded personal hooks usable in outreach.",
    ),
    FieldSpec(
        key="contact.facet.openers",
        description="Three grounded first-line openers for a cold message.",
    ),
    FieldSpec(
        key="contact.facet.voice_quote",
        description=(
            "A verbatim quote from the person's own long-form media, with its media_url and "
            "timestamp."
        ),
    ),
)


def _load_poc_catalog() -> FieldCatalog:
    """Load the PoC's field catalog by path and map it onto :class:`FieldCatalog`.

    ``ACCOUNT_FIELDS``/``CONTACT_FIELDS`` are ``key: (value_type, json_schema, description)``;
    ``FACET_FIELDS`` appends a default use-class as a fourth element, which this shape does not
    carry — the first three are read from both. The facet section is then extended with
    :data:`REGISTERED_SINCE_THE_POC`, so the catalog under test is the production one.
    """
    spec = importlib.util.spec_from_file_location("arv2_poc_field_catalog", CATALOG_SOURCE)
    assert spec is not None and spec.loader is not None, CATALOG_SOURCE
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def section(fields: Mapping[str, Sequence[object]]) -> tuple[FieldSpec, ...]:
        return tuple(
            FieldSpec(
                key=key,
                description=str(entry[2]),
                value_schema=entry[1] if isinstance(entry[1], Mapping) else None,
            )
            for key, entry in fields.items()
        )

    return FieldCatalog(
        account=section(module.ACCOUNT_FIELDS),
        contact=section(module.CONTACT_FIELDS),
        facet=(*section(module.FACET_FIELDS), *REGISTERED_SINCE_THE_POC),
    )


@pytest.fixture(scope="session")
def poc_catalog() -> FieldCatalog:
    return _load_poc_catalog()


@pytest.fixture
def client(make_caller: Callable[..., ProviderCaller], live_secrets: Secrets) -> StructuringClient:
    """The client under test, on the shipped model knob and the shipped gateway base URL."""
    require_secret(live_secrets, "openrouter_api_key")
    api_key = live_secrets.openrouter_api_key
    assert api_key is not None
    return StructuringClient(
        make_caller(),
        api_key=api_key,
        base_url=GatewayConfig().base_url,
        model=Settings().arv2_structuring_model,
    )


def _zafran_bundle() -> str:
    """The z7 bundle's two prose sources: the Exa deep report and the own-site page texts."""
    root = CONTEXT / "arv2-one-account-aiark"
    deep = (root / "report_account_zafran_deep.md").read_text(encoding="utf-8")
    own = json.loads((root / "raw" / "z2_own_site.json").read_text(encoding="utf-8"))
    own_text = "\n\n".join(
        f"### {record.get('url')}\n{(record.get('text') or '')[:5000]}"
        for record in (own.get("results") or [])
    )
    return (
        "=== SOURCE A: Exa deep-reasoning dossier (2026-09-02) ===\n"
        f"{deep}\n\n"
        "=== SOURCE B: zafran.io own-site pages (Exa /contents livecrawl 2026-09-02) ===\n"
        f"{own_text}\n"
    )


def _nick_fisher_bundle() -> str:
    """The person bundle's research material only, from the first ``=== MATERIAL`` line on.

    The file's head is the proof-of-concept's own prompt — its SUBJECT block, its closed key list
    with "[PROPOSED — new field]" labels, its charter categories and its "Return STRICT JSON"
    envelope — not research material. A production bundle is assembled from sources by the R2/R3
    agents and never contains a prompt, so feeding the head in would test an input production
    cannot produce. The client's bundle fence and closing reminder stay exactly as they are: they
    are the defence for a real bundle that quotes a hostile page.
    """
    text = (CONTEXT / "arv2-person-depth" / "structuring_bundle_nick_fisher.txt").read_text(
        encoding="utf-8"
    )
    lines = text.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.startswith("=== MATERIAL")), None
    )
    assert start is not None, "no '=== MATERIAL' section in the person bundle"
    return "".join(lines[start:])


def _report(title: str, output: StructuredOutput, bundle: str) -> tuple[Counter[str], float]:
    """Print the tallies a run is judged on, and return the two the assertions read."""
    verdicts = Counter(claim.evidence_verbatim for claim in output.claims)
    exact_rate = verdicts["EXACT"] / len(output.claims) if output.claims else 0.0
    priorities = Counter(claim.priority for claim in output.claims)
    schema = Counter(str(claim.schema_valid) for claim in output.claims)
    print(
        f"\n[{title}] bundle={len(bundle)} chars  claims={len(output.claims)} "
        f"proposed={len(output.proposed)} negatives={len(output.negatives)}\n"
        f"  verbatim={dict(verdicts)} exact_rate={exact_rate:.2f}\n"
        f"  priority={dict(sorted(priorities.items()))} schema_valid={dict(schema)}\n"
        f"  cost_usd={output.cost_usd} request_id={output.request_id}\n"
        f"  raw_ref={output.raw_ref}"
    )
    return verdicts, exact_rate


def _assert_metered(output: StructuredOutput, arv2_raw_root: Path) -> None:
    """The ledger's result row carries OpenRouter's own cost, not the estimate."""
    assert output.cost_usd is not None and output.cost_usd > 0
    assert output.request_id is not None
    assert output.raw_ref is not None and Path(output.raw_ref).exists()

    call_id = json.loads(Path(output.raw_ref).read_text(encoding="utf-8"))["call_id"]
    rows = [
        json.loads(line)
        for line in (arv2_raw_root / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    mine = [row for row in rows if row["call_id"] == call_id]
    assert [row["phase"] for row in mine] == ["estimate", "result"]
    assert mine[1]["outcome"] == "ok"
    assert Decimal(str(mine[1]["cost_usd"])) == output.cost_usd
    assert mine[1]["provider_request_id"] == output.request_id
    assert mine[1]["extras"]["cost_source"] == "metered", (
        "anything but `metered` means the estimate stood in and no metering was read"
    )

    # The uniform provision: the structured output carries the whole money view of the call that
    # produced it, and it is the same row — not a softer copy of it.
    assert output.cost is not None
    assert output.cost.cost_source == "metered"
    assert output.cost.cost_usd == output.cost_usd
    assert output.cost.ledger_row_id == mine[1]["row_id"]
    assert output.cost.raw_ref == output.raw_ref
    assert (output.cost.provider, output.cost.operation) == ("openrouter", "chat/completions")


def _assert_closed_catalog(output: StructuredOutput, catalog: FieldCatalog) -> None:
    """Every kept key is registered, and every re-filed one genuinely is not."""
    registered = catalog.keys()
    assert all(claim.field_key in registered for claim in output.claims)
    for proposal in output.proposed:
        if proposal.origin == UNREGISTERED_KEY_ORIGIN:
            assert proposal.suggested_key not in registered


def test_the_poc_catalog_loads_with_its_recorded_key_counts(poc_catalog: FieldCatalog) -> None:
    """24 / 8 / 15 — if the catalog shrank, every live assertion below would soften silently.

    12 facet keys come from the PoC file; the 3 that master plan §4 registered afterwards are
    added by :data:`REGISTERED_SINCE_THE_POC`, so this is the production facet set.
    """
    assert (len(poc_catalog.account), len(poc_catalog.contact), len(poc_catalog.facet)) == (
        24,
        8,
        15,
    )
    assert len(poc_catalog.keys()) == 47
    assert {spec.key for spec in REGISTERED_SINCE_THE_POC} <= poc_catalog.keys()


def test_zafran_structures_into_registered_claims_with_verbatim_evidence(
    client: StructuringClient, poc_catalog: FieldCatalog, arv2_raw_root: Path
) -> None:
    """The z7 bundle, one account per call. The EXACT rate is the honesty measure."""
    bundle = _zafran_bundle()

    output = client.structure_account(
        AccountSubject(name="Zafran Security", domain="zafran.io"), bundle, poc_catalog
    )

    _, exact_rate = _report("zafran", output, bundle)
    assert len(output.claims) >= 15
    _assert_closed_catalog(output, poc_catalog)
    assert all(claim.priority in {1, 2, 3} for claim in output.claims)
    assert exact_rate >= EXACT_VERBATIM_FLOOR, f"EXACT verbatim rate {exact_rate:.2f}"
    _assert_metered(output, arv2_raw_root)


def test_probook_structures_from_its_account_report(
    client: StructuringClient, poc_catalog: FieldCatalog, arv2_raw_root: Path
) -> None:
    """A second account proves the call is not tuned to one bundle's prose."""
    bundle = (CONTEXT / "arv2-clue-sample-v3" / "account_report.md").read_text(encoding="utf-8")

    output = client.structure_account(
        AccountSubject(name="Probook", domain="probook.ai"), bundle, poc_catalog
    )

    _report("probook", output, bundle)
    assert len(output.claims) >= 10
    _assert_closed_catalog(output, poc_catalog)
    assert all(claim.priority in {1, 2, 3} for claim in output.claims)
    _assert_metered(output, arv2_raw_root)


def test_nick_fisher_structures_as_one_person_per_call(
    client: StructuringClient, poc_catalog: FieldCatalog, arv2_raw_root: Path
) -> None:
    """The person path over the PoC's own person material, priorities on the person rubric."""
    bundle = _nick_fisher_bundle()

    output = client.structure_person(
        PersonSubject(
            name="Nick Fisher",
            company="Zafran Security",
            linkedin_url="https://www.linkedin.com/in/nicholastfisher",
        ),
        bundle,
        poc_catalog,
    )

    _report("nick_fisher", output, bundle)
    # Ruling (R1 review, 2026-09-07): the R1 gate proves the client works live; yield floors are
    # R3's answer-key comparison. Six material-only runs gave 7–11 kept claims plus 1–2 proposed,
    # so the floor is on the evidence-bound rows the call produced, kept and proposed together.
    assert len(output.claims) + len(output.proposed) >= 8
    _assert_closed_catalog(output, poc_catalog)
    assert all(claim.priority in {1, 2, 3} for claim in output.claims)
    _assert_metered(output, arv2_raw_root)


def test_probook_intent_sweep_parses_and_keeps_only_registered_keys(
    client: StructuringClient, poc_catalog: FieldCatalog, arv2_raw_root: Path
) -> None:
    """The second mode, live, over the same Probook material the broad pass reads.

    What is asserted is the **shape**, not the count: the sweep is deliberately narrow (at most
    four rows, and an empty answer is the correct answer for material carrying no buying-intent
    statement), so a yield floor here would fail for the one reason the mode is designed to allow.
    The comparison worth having — what the sweep finds that the broad pass missed — is the answer
    key's job in R3, not this gate's.
    """
    bundle = (CONTEXT / "arv2-clue-sample-v3" / "account_report.md").read_text(encoding="utf-8")

    output = client.structure_account(
        AccountSubject(name="Probook", domain="probook.ai"),
        bundle,
        poc_catalog,
        mode="intent_sweep",
    )

    _report("probook-intent-sweep", output, bundle)
    print(f"  dropped_rows={output.dropped_rows}")
    assert output.mode == "intent_sweep"
    assert len(output.claims) <= 4, "the sweep is capped at four rows, best first"
    # The cap is enforced in code, so it can no longer be the thing that proves the mode works —
    # a drifted answer would be silently truncated to four and look identical to a real sweep.
    # ``dropped_rows`` is where that drift now shows: non-zero means the model answered a sweep
    # request with a broad answer, which is exactly the defect the two-turn prompt swap fixes.
    assert output.dropped_rows == 0, (
        f"the model returned {len(output.claims) + output.dropped_rows} rows for a 4-row sweep: "
        "the sweep prompt is drifting broad again"
    )
    _assert_closed_catalog(output, poc_catalog)
    assert all(claim.priority in {1, 2, 3} for claim in output.claims)
    assert all(claim.evidence_span.strip() for claim in output.claims), (
        "a sweep row with no quote is not a row"
    )
    _assert_metered(output, arv2_raw_root)
