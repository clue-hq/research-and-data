# Read-tools hotfix Implementation Plan (Lane 1, plan 0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Head of ABM can read a researched account and a discovery run today: the discovery read passes its own output contract, the account read never overflows the governed receipt, a wrong claim prefix is answered with the right ones, and an honest read refusal cannot kill the turn.

**Architecture:** Four surgical repairs on the plan-4 code (`clue_api.arv2.read_tools`) and one on the runtime's repair budget (`agent_runtime_wiring._tool_failure`), followed by the grant recipe (skill v27, profile v50, digests re-measured; recipe v26 unchanged because no tool address moves). No schema migration. Nothing here anticipates the reorganisation spec; plan 4 of that spec (paged and spilled reads) replaces the byte bound introduced here with a real cursor.

**Tech Stack:** Python 3.12, pydantic 2, SQLAlchemy async, pytest with `rollback_conn` DB fixtures, the toolbelt runner, the agent catalog.

**Spec:** `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` §1 (the observed failures) and W10; findings in `_memory/2026-09-13-live-walk-findings-and-workspace-reorg.md`.

## Global Constraints

- **Receipt bound:** `GovernedOperationReceipt.reference_values` canonical JSON must be ≤ 16 384 bytes (`clue_agents/execution.py:149`). This plan bounds every read tool's `references` to `READ_REFERENCES_BUDGET_BYTES = 12 * 1024`, encoded exactly as the receipt encodes (`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`).
- **Contract validation path:** every tool result is re-validated by `clue_toolbelt.runner.validate_tool_output_references(output_model, references)` in JSON mode. Offline tests of a tool's result MUST go through that function.
- **Display gate unchanged:** `_account_claims` keeps holding back sensitive, unverified tier-4 (under `settings.verification_enabled`) and outreach-unsafe claims, counted in `excluded`.
- **Grant recipe:** a schema change moves the tool's digest → new immutable skill copy (`v27`) with re-measured `input_schema_sha256`/`output_schema_sha256`, new profile copy (`v50`) pinning it, `C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM] = "v50"`, `PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v50"`, the catalog and registry tests' expected lists/digests updated. Recipe stays `recipe0-stage0-v26` (no address added or dropped). Never edit v26/v49 in place.
- **Skill text is founder-reviewed:** the §7c wording in Task 5 is the text to present; do not paraphrase it further without the founder.
- **Tests:** offline suites run without `.env` sourced; DB suites only against the lane DB with `--ignore-glob='*_live.py' -p no:cacheprovider`. Never run `*_live.py`.
- **Commits:** local only, no push, no AI attribution.

---

### Task 1: `read_discovery_run@1` passes its own output contract

**Files:**
- Modify: `platform/api/clue_api/arv2/read_tools.py:587-602` (`DiscoveryCandidateView`)
- Test: `tests/api/test_arv2_read_tools.py` (new test beside `test_the_discovery_read_asks_about_the_ambient_workspace_and_serves_the_run`)

**Interfaces:**
- Consumes: `clue_toolbelt.runner.validate_tool_output_references(output_model, references)`.
- Produces: `DiscoveryCandidateView.pass_` accepting `pass` and `pass_` on input, serializing as `pass`. The output digest of `read_discovery_run@1` moves (Task 5 re-measures it).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_arv2_read_tools.py — add to the imports:
from clue_api.arv2.read_tools import ReadDiscoveryRunOutput
from clue_toolbelt.runner import validate_tool_output_references


def test_the_discovery_read_s_result_passes_the_runner_s_own_output_validation() -> None:
    """The live defect: the tool dumped ``pass`` by alias and the runner re-validated the JSON
    against a model that only accepted ``pass_`` — every call was a ToolContractViolation."""

    async def scenario() -> None:
        tool = ReadDiscoveryRunTool(_FakeService(discovery=_discovery()))
        result = await tool.invoke(
            ReadDiscoveryRunInput(project_id=PROJECT, run_id=DISCOVERY_RUN_ID, candidate_limit=10),
            _context(),
        )

        canonical = validate_tool_output_references(ReadDiscoveryRunOutput, result.references)

        assert canonical["candidates"] == [
            {
                "name": "Alpha Health",
                "domain": "alpha.example",
                "pass": "relaxed",
                "disposition": "pass",
                "decision": "approved",
                "fit": 0.9,
            }
        ]

    run_async(scenario())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/api/test_arv2_read_tools.py -k passes_the_runner -p no:cacheprovider -q`
Expected: FAIL with `ValidationError: … candidates.0.pass_ Field required`.

- [ ] **Step 3: Accept the schema's word on input too**

```python
# platform/api/clue_api/arv2/read_tools.py — replace the pass_ field of DiscoveryCandidateView
from pydantic import AliasChoices, BaseModel, ConfigDict, Field  # AliasChoices is new

class DiscoveryCandidateView(BaseModel, frozen=True):
    """One company a discovery run surfaced, with the verdict the verifier gave it."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: str
    domain: str
    #: Which §4 pass surfaced it — ``strict`` (the full criteria) or ``relaxed`` (the widened
    #: re-search). ``pass`` is the schema's word on both sides of the wire; the trailing underscore
    #: is Python's. The runner re-validates a dumped result in JSON mode, so the model must accept
    #: what it serializes — the 2026-09-13 live defect was a serialization-only alias.
    pass_: str = Field(
        validation_alias=AliasChoices("pass", "pass_"),
        serialization_alias="pass",
    )
    disposition: str
    decision: str | None
    fit: float | None
```

Keep `frozen=True` in the class arguments AND in `model_config` (pydantic merges them; the explicit config is what carries `populate_by_name`). Keep the `model_dump(by_alias=True)` in `ReadDiscoveryRunTool.invoke`.

- [ ] **Step 4: Run the test and the file**

Run: `.venv/bin/pytest tests/api/test_arv2_read_tools.py -p no:cacheprovider -q`
Expected: PASS (the new test and every existing one; the constructor call `DiscoveryCandidateView(pass_=…)` in the fixture still works via `populate_by_name`).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/read_tools.py tests/api/test_arv2_read_tools.py
git commit -m "fix(arv2): read_discovery_run accepts the schema's 'pass' on input so its result passes the runner's own validation"
```

---

### Task 2: Every read's `references` fits the governed receipt

**Files:**
- Modify: `platform/api/clue_api/arv2/read_tools.py` (bounds block at 325-345; `_overview_sections` 395-440; `_account_claims` 452-534; `read_account_research` 536-586; `DbArv2ReadService.read_account_research`; `ReadAccountResearchInput/Output` 970-992; `ReadAccountResearchTool.invoke`)
- Test: `tests/arv2/test_read_tools_db.py` (replace `test_the_claims_read_is_bounded_at_the_cap_and_says_so`, extend `test_a_long_overview_body_is_capped_and_says_so`), `tests/api/test_arv2_read_tools.py` (a bound test through the runner)

**Interfaces:**
- Consumes: `_seed_claim`, `_seed_block`, `_seed_account`, `seed_project`, `load_display_recipes`, `rollback_conn`, `VERIFYING` (existing helpers in the DB test).
- Produces:
  - `READ_REFERENCES_BUDGET_BYTES: int = 12 * 1024` and `receipt_bytes(value: object) -> int` (module-level, exported).
  - `AccountResearch` gains `offset: int` and `next_offset: int | None`.
  - `read_account_research(conn, *, workspace_id, account_entity_id, section, settings, field_prefix=None, offset=0)`.
  - `Arv2ReadService.read_account_research(..., offset: int)` and `DbArv2ReadService` likewise.
  - `ReadAccountResearchInput.offset: int = Field(default=0, ge=0)`; `ReadAccountResearchOutput.offset: int`, `.next_offset: int | None`, `.prefixes: dict[str, int]` (Task 3 fills `prefixes`; declare it here as `{}`).

- [ ] **Step 1: Write the failing DB test for the claims bound**

```python
# tests/arv2/test_read_tools_db.py — replace test_the_claims_read_is_bounded_at_the_cap_and_says_so
from clue_api.arv2.read_tools import (  # extend the existing import
    READ_REFERENCES_BUDGET_BYTES,
    receipt_bytes,
)


def test_the_claims_read_fits_the_governed_receipt_and_pages_the_rest() -> None:
    """The 2026-09-13 live defect: 72 claims built a valid result the runtime then refused
    ("bounded operation receipt exceeds 16 KiB"). The read now stops at the byte budget, says so,
    and names the offset the next call continues from."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            # ~400 bytes of evidence each: 72 of them is ~30 KiB, the shape of the live account.
            for index in range(72):
                await _seed_claim(
                    conn,
                    claims,
                    project,
                    account,
                    label=f"claim_{index}",
                    field_key=f"account.open_requisitions.role_{index:03d}",
                    value={"title": f"Role {index}", "posted": "2026-09-01"},
                    evidence_span=("Hiring now: " + ("clinical staff, ") * 24).strip(),
                    source_url=f"https://alpha.example/jobs/{index}",
                )

            first = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=VERIFYING,
            )
            assert first.truncated is True
            assert first.offset == 0
            assert first.next_offset is not None and 0 < first.next_offset < 72
            assert len(first.claims) == first.next_offset
            assert receipt_bytes([view.model_dump() for view in first.claims]) <= (
                READ_REFERENCES_BUDGET_BYTES
            )

            # Walk the rest: the pages partition the kept claims, in order, without overlap.
            seen = [view.claim_id for view in first.claims]
            offset = first.next_offset
            while offset is not None:
                page = await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="claims",
                    settings=VERIFYING,
                    offset=offset,
                )
                assert page.offset == offset
                seen.extend(view.claim_id for view in page.claims)
                offset = page.next_offset
            assert len(seen) == 72 and len(set(seen)) == 72

    run_async(scenario())
```

`_seed_claim` forwards `**overrides` to `write_claim`; confirm `evidence_span` and `source_url` are accepted names there (they are the claim columns the read serves) before running.

- [ ] **Step 2: Run it to verify it fails**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/arv2/test_read_tools_db.py -k fits_the_governed_receipt --ignore-glob='*_live.py' -p no:cacheprovider -q`
Expected: FAIL with `TypeError: read_account_research() got an unexpected keyword argument 'offset'`.

- [ ] **Step 3: Add the budget, the encoder and the paging**

```python
# platform/api/clue_api/arv2/read_tools.py — beside the existing bounds (after BODY_CHARS)

#: The budget for one read's ``references``. The runtime records every governed result as a
#: ``GovernedOperationReceipt`` whose canonical ``reference_values`` must stay under 16 KiB
#: (``clue_agents/execution.py``); a result over it is discarded *after* the read ran, which is
#: how 72 claims became "the agent cannot read this account" on 2026-09-13. 12 KiB leaves room
#: for the envelope fields (ids, name, counts) and for the receipt's own wrapper.
READ_REFERENCES_BUDGET_BYTES = 12 * 1024


def receipt_bytes(value: object) -> int:
    """How many bytes ``value`` occupies in a receipt — the receipt's own encoding, so the bound
    measured here is the bound the runtime enforces."""

    return len(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    )


def _take_within_budget(
    items: Sequence[dict[str, Any]], *, budget: int
) -> tuple[int, bool]:
    """How many leading ``items`` fit in ``budget`` bytes when encoded as one JSON array.

    Always admits at least one item (a single over-budget item is the caller's to clip), and
    returns whether anything was left out. Linear, not bisected: pages are a few dozen items.
    """

    if not items:
        return 0, False
    used = 2  # the array's brackets
    count = 0
    for item in items:
        size = receipt_bytes(item) + (1 if count else 0)  # the comma
        if count and used + size > budget:
            break
        used += size
        count += 1
    return count, count < len(items)
```

Then change `AccountResearch`:

```python
@dataclass(frozen=True, slots=True)
class AccountResearch:
    account_entity_id: str
    account_name: str
    section: str
    overview: tuple[AccountOverviewSection, ...]
    claims: tuple[AccountClaimView, ...]
    truncated: bool
    excluded: dict[str, int]
    #: Where this page started in the account's servable claims (``0`` for the overview).
    offset: int
    #: Where the next page starts, or ``None`` when this page ends the list.
    next_offset: int | None
    #: The account's claim families with their servable counts — the prefixes a narrowed read
    #: may ask for (Task 3 fills it; ``{}`` until then).
    prefixes: dict[str, int]
```

Change `_account_claims` to page and to bound:

```python
async def _account_claims(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_uuid: UUID,
    field_prefix: str | None,
    settings: Settings,
    offset: int,
) -> tuple[tuple[AccountClaimView, ...], bool, dict[str, int], int | None]:
    ...  # the load, the prefix filter, the gate loop are unchanged, producing `kept`
    if offset >= len(kept) and offset > 0:
        raise Arv2ReadRefused(
            "offset_past_end",
            f"this account has {len(kept)} servable claims; offset {offset} is past the end",
        )
    window = kept[offset : offset + MAX_CLAIMS]
    views: list[AccountClaimView] = []
    for claim in window:
        evidence, evidence_truncated = _clip(claim.evidence_span or "", EVIDENCE_CHARS)
        views.append(AccountClaimView(...))  # unchanged construction
    fitted, cut = _take_within_budget(
        [view.model_dump() for view in views], budget=READ_REFERENCES_BUDGET_BYTES
    )
    served = tuple(views[:fitted])
    end = offset + len(served)
    truncated = cut or end < len(kept)
    return served, truncated, excluded, (end if truncated else None)
```

Change `_overview_sections` to bound the page the same way — after building `sections`:

```python
    fitted, cut = _take_within_budget(
        [section.model_dump() for section in sections], budget=READ_REFERENCES_BUDGET_BYTES
    )
    if fitted == 0 or (fitted == 1 and cut and len(sections) > 1):
        # One section alone is over budget: clip its body to what fits rather than serve nothing.
        pass
    return tuple(sections[:fitted]), cut
```

Replace the `pass` branch with a real clip: compute `room = READ_REFERENCES_BUDGET_BYTES - receipt_bytes({**sections[0].model_dump(), "body_text": ""})` and rebuild `sections[0]` with `_clip(sections[0].body_text, max(room, 200))`. Return type becomes `tuple[tuple[AccountOverviewSection, ...], bool]` and `read_account_research` sets `truncated` from it for the overview branch (`offset=0`, `next_offset=None`: the overview is not paged in this hotfix; a truncated overview tells the model to read claims).

Thread `offset` through `read_account_research` (parameter `offset: int = 0`; refuse `offset != 0` on the overview branch with `Arv2ReadRefused("offset_not_paged", "the overview is not paged; omit offset")`), through `Arv2ReadService`/`DbArv2ReadService.read_account_research(..., offset: int)`, and through the tool:

```python
class ReadAccountResearchInput(ToolInput):
    account_entity_id: str
    section: Literal["overview", "claims"] = "overview"
    #: Claims only: a claim family — one of the ``prefixes`` a previous read of this account
    #: returned (for example ``account.resonance`` or ``core``). A prefix that matches nothing is
    #: refused with the prefixes that exist.
    field_prefix: str | None = Field(default=None, max_length=80)
    #: Claims only: continue from ``next_offset`` of the previous page. ``0`` starts over.
    offset: int = Field(default=0, ge=0)


class ReadAccountResearchOutput(ToolOutput):
    account_entity_id: str
    account_name: str
    section: str
    overview: tuple[AccountOverviewSection, ...]
    claims: tuple[AccountClaimView, ...]
    #: More exists than this page holds: continue with ``offset = next_offset`` (claims), or read
    #: the claims when a long overview was cut.
    truncated: bool
    excluded: dict[str, int]
    offset: int
    next_offset: int | None
    prefixes: dict[str, int]
```

and in `ReadAccountResearchTool.invoke` pass `offset=inputs.offset` and copy `offset`, `next_offset`, `prefixes` into the output.

- [ ] **Step 4: Run the DB tests**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/arv2/test_read_tools_db.py --ignore-glob='*_live.py' -p no:cacheprovider -q`
Expected: PASS, including the reworked overview-cap test (add the assertion that an overview whose sections total more than the budget comes back `truncated=True` and that `receipt_bytes([s.model_dump() for s in research.overview]) <= READ_REFERENCES_BUDGET_BYTES`).

- [ ] **Step 5: Write the runner-path bound test (offline)**

```python
# tests/api/test_arv2_read_tools.py
from clue_api.arv2.read_tools import READ_REFERENCES_BUDGET_BYTES, receipt_bytes


def test_the_account_read_s_result_fits_the_governed_receipt() -> None:
    """The bound is measured where the runtime measures it: on the canonical references."""

    async def scenario() -> None:
        big = AccountResearch(
            account_entity_id=ACCOUNT_ID,
            account_name="Alpha Health",
            section="claims",
            overview=(),
            claims=tuple(
                AccountClaimView(
                    claim_id=f"{index:08d}-4444-5444-8444-444444444444",
                    field_key="account.open_requisitions",
                    value={"title": f"Role {index}"},
                    source_url="https://alpha.example/jobs",
                    evidence="x" * 240,
                    evidence_truncated=True,
                    tier=3,
                    verification_status="unverified",
                    outreach_safe=True,
                    collected_at="2026-09-12T08:00:00+00:00",
                )
                for index in range(40)
            ),
            truncated=True,
            excluded={"sensitive": 0, "unverified": 0, "outreach_unsafe": 0},
            offset=0,
            next_offset=40,
            prefixes={"account.open_requisitions": 40},
        )
        tool = ReadAccountResearchTool(_FakeService(research=big))
        result = await tool.invoke(
            ReadAccountResearchInput(account_entity_id=ACCOUNT_ID, section="claims"), _context()
        )
        canonical = validate_tool_output_references(ReadAccountResearchOutput, result.references)
        # The service is trusted to have bounded the page; the tool adds < 1 KiB of envelope.
        assert receipt_bytes(canonical) < 16_384

    run_async(scenario())
```

Run: `.venv/bin/pytest tests/api/test_arv2_read_tools.py -p no:cacheprovider -q` — PASS (update `_FakeService`/`_research()` fixtures for the three new `AccountResearch` fields).

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/read_tools.py tests/arv2/test_read_tools_db.py tests/api/test_arv2_read_tools.py
git commit -m "fix(arv2): the account read fits the governed receipt — claims paged by offset under a byte budget, a long overview clipped and flagged"
```

---

### Task 3: A wrong prefix is answered with the right ones

**Files:**
- Modify: `platform/api/clue_api/arv2/read_tools.py` (`_account_claims`, the `no_claims_under_prefix` refusal, `prefixes` on the result; the `model_description` of `ReadAccountResearchTool`)
- Test: `tests/arv2/test_read_tools_db.py`

**Interfaces:**
- Produces: `claim_prefixes(claims: Iterable[Claim]) -> dict[str, int]` (module-level; the family is the first two dotted segments of `field_key`, e.g. `core.legal_name` → `core.legal_name`? No: `account.resonance.culture` → `account.resonance`; `core.legal_name` → `core.legal_name`. Rule: two segments, so a two-segment key is its own family). `AccountResearch.prefixes` filled from the *servable* (gated) claims of the whole account, not the page.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_prefix_that_matches_nothing_is_refused_with_the_prefixes_that_exist() -> None:
    """The live turn asked for ``firmographic`` and was told only that nothing matched."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            await _seed_claim(conn, claims, project, account, label="a", field_key="core.legal_name", value="Alpha Health LLC")
            await _seed_claim(conn, claims, project, account, label="b", field_key="account.resonance.culture", value="warm")
            await _seed_claim(conn, claims, project, account, label="c", field_key="account.resonance.frustrations", value="fax")

            with pytest.raises(Arv2ReadRefused) as refused:
                await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="claims",
                    settings=VERIFYING,
                    field_prefix="firmographic",
                )
            assert refused.value.code == "no_claims_under_prefix"
            assert "account.resonance (2)" in str(refused.value)
            assert "core.legal_name (1)" in str(refused.value)

    run_async(scenario())


def test_the_claims_read_names_the_account_s_claim_families() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            await _seed_claim(conn, claims, project, account, label="a", field_key="core.legal_name", value="Alpha Health LLC")
            await _seed_claim(conn, claims, project, account, label="b", field_key="account.resonance.culture", value="warm")

            research = await read_account_research(
                conn, workspace_id=project.workspace_id, account_entity_id=str(account),
                section="claims", settings=VERIFYING, field_prefix="core",
            )
            # The families are the whole account's, so a narrowed page still shows what else exists.
            assert research.prefixes == {"account.resonance": 1, "core.legal_name": 1}
            assert [view.field_key for view in research.claims] == ["core.legal_name"]

    run_async(scenario())
```

- [ ] **Step 2: Run to verify they fail**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/arv2/test_read_tools_db.py -k "prefixes_that_exist or claim_families" --ignore-glob='*_live.py' -p no:cacheprovider -q`
Expected: FAIL (`prefixes == {}`; refusal text lacks the families).

- [ ] **Step 3: Implement**

```python
def claim_prefixes(claims: Iterable[Claim]) -> dict[str, int]:
    """The claim families on an account: the first two dotted segments of each field key, with a
    count. Sorted by count, then name, so the model reads the biggest family first."""

    counts: Counter[str] = Counter(
        ".".join(str(claim.field_key).split(".")[:2]) for claim in claims
    )
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
```

In `_account_claims`, compute the gate over **all** claims first (so `prefixes` reflects servable claims), then filter by prefix:

```python
    gated: list[Claim] = []
    for claim in claims:
        ...  # the existing three checks, counting into `excluded`
        gated.append(claim)
    prefixes = claim_prefixes(gated)
    kept = [c for c in gated if field_prefix is None or str(c.field_key).startswith(field_prefix)]
    if not kept:
        listed = ", ".join(f"{name} ({count})" for name, count in list(prefixes.items())[:12])
        raise Arv2ReadRefused(
            "no_claims_under_prefix",
            f"this account has claims, but none under {field_prefix!r}; its families are: {listed}",
        )
```

Return `prefixes` as a fifth element and set it on `AccountResearch`. Note the ordering change: previously the prefix filter ran before the gate, so `excluded` counted only matching claims; now `excluded` counts the whole account. Update the docstring and the existing gate test's expectation if it asserted per-prefix counts.

Update the tool's `model_description` (the model reads this):

```python
    model_description = (
        "Read what research found about one account. section='overview' returns the written "
        "overview sections (prose citing claim ids); when the overview is not written yet the "
        "read refuses with overview_not_written — then read section='claims'. section='claims' "
        "returns the claims the account pages show, one page at a time: follow next_offset "
        "until it is null, or narrow with field_prefix to one of the families listed in "
        "'prefixes' (e.g. 'account.resonance', 'core'). Sensitive, unverified tier-4 and "
        "outreach-unsafe claims are held back and counted in 'excluded'. Read this before "
        "saying anything specific about an account. Effect-free."
    )
```

- [ ] **Step 4: Run the DB file and the offline file**

Run both commands from Tasks 1–2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/read_tools.py tests/arv2/test_read_tools_db.py tests/api/test_arv2_read_tools.py
git commit -m "fix(arv2): a claims read names the account's claim families, and a wrong prefix is refused with the right ones"
```

---

### Task 4: An honest read refusal does not spend the repair budget (W10)

**Files:**
- Modify: `platform/api/clue_api/agent_runtime_wiring.py:790-812` (the `operation_failed` branch) and `:882-925` (`_tool_failure`)
- Test: `tests/agents/test_governed_tool_feedback.py`

**Interfaces:**
- Consumes: `descriptor.effect_class` (`ToolEffectClass.READ`) in the `_governed_tool` closure; `OperationFailure.error_type`.
- Produces: `_tool_failure(..., budgeted: bool = True)`; the `agent.tool_repair` log line gains `budgeted`.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_governed_tool_feedback.py
def _read_call(call_id: str) -> AIMessage:
    """A model turn that calls an effect-free read (the shape of the 2026-09-13 fan-out)."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": call_id,
                "name": "read_project_accounts",
                "args": {"project_id": "prj_governed_feedback", "limit": 25, "offset": 0},
            }
        ],
    )


class _RefusingReadExecution(_RefusingExecution):
    """Refuses with the read tools' own error type."""

    async def execute(self, *, plan: ValidatedPlan) -> AsyncIterator[ExecutionProgress]:
        self.executed.append(plan)
        operation = plan.operations[0]
        if len(self.executed) <= self.refusals:
            yield ExecutionProgress(
                execution_id=plan.execution_id,
                status="failed",
                failed_node_keys=(operation.node_key,),
                failures=(
                    OperationFailure(
                        node_key=operation.node_key,
                        address=operation.address,
                        error_type="PreconditionFailed",
                        message="tool preconditions unmet: overview_not_written",
                    ),
                ),
            )
            return
        async for progress in super().execute(plan=plan):  # the committing path
            yield progress


def test_honest_read_refusals_do_not_spend_the_repair_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """W10: five parallel account reads answered ``overview_not_written`` killed a live turn.
    A PreconditionFailed from an effect-free read is information, not a misread contract."""

    emitted: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        wiring_module,
        "log",
        SimpleNamespace(warning=lambda event, **fields: emitted.append((event, fields))),
    )
    execution = _RefusingReadExecution(refusals=5)
    outcome, calls = _run(
        (*(_read_call(f"read-{ordinal}") for ordinal in range(5)), _finalize_call()),
        execution=execution,
    )

    assert outcome.status is not AgentExecutionStatus.FAILED
    assert [fields["budgeted"] for _, fields in emitted] == [False] * 5
    assert all(fields["exhausted"] is False for _, fields in emitted)
    assert len(calls.batches) == 6
```

`_finalize_call()` is whatever this file already uses as the model's closing turn in `test_a_refused_operation_is_repaired_from_visible_tool_feedback` (the response after the repaired call); reuse it by name. If the profile's `read_project_accounts` needs the `project` pin in `constitution(...)`, extend the helper's constitution the way the entity-research tests do (`tests/api/test_entity_research_cutover_r10.py` shows a pinned constitution).

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/agents/test_governed_tool_feedback.py -k honest_read -p no:cacheprovider -q`
Expected: FAIL — `outcome.status is FAILED` after the fourth refusal, and `KeyError: 'budgeted'`.

- [ ] **Step 3: Implement**

In the `operation_failed` branch of `invoke` (after computing `failures`):

```python
                # W10 (2026-09-13): an effect-free read that refuses by precondition — the overview
                # is not written, no claims under that prefix, no discovery run — has answered the
                # question it was asked. It is not a misread argument contract, so it does not
                # spend the repair budget; a parallel fan-out of five such reads killed a live turn.
                honest_read = descriptor.effect_class is ToolEffectClass.READ and bool(
                    failures
                ) and all(failure.error_type == "PreconditionFailed" for failure in failures)
                return self._tool_failure(
                    error="operation_failed",
                    ...,  # unchanged
                    budgeted=not honest_read,
                )
```

and in `_tool_failure`:

```python
    def _tool_failure(self, *, error, address, node_key, error_type, reasons, raise_when_exhausted,
                      budgeted: bool = True) -> str:
        if budgeted:
            self._tool_failures += 1
        exhausted = budgeted and self._tool_failures > _MAX_GOVERNED_TOOL_FAILURES
        log.warning(
            "agent.tool_repair",
            address=address, node_key=node_key, error=error, error_type=error_type,
            reasons=list(reasons), attempt=self._tool_failures, exhausted=exhausted,
            budgeted=budgeted,
        )
        ...
```

Import `ToolEffectClass` from `clue_toolbelt` if the module does not already. Update the docstring of `_tool_failure` with the W10 sentence.

- [ ] **Step 4: Run the whole feedback file**

Run: `.venv/bin/pytest tests/agents/test_governed_tool_feedback.py -p no:cacheprovider -q`
Expected: PASS; the existing exhaustion test still sees `[1, 2, 3, 4]` attempts and `budgeted=True`.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/agent_runtime_wiring.py tests/agents/test_governed_tool_feedback.py
git commit -m "fix(agent-runtime): an honest precondition refusal from an effect-free read does not spend the repair budget (W10)"
```

---

### Task 5: The grant — skill v27, profile v50, digests

**Files:**
- Create: `platform/agents/catalog/skills/stage0-interview/v27/SKILL.md` (copy of v26), `platform/agents/catalog/profiles/head-of-abm/v50/profile.yaml` (copy of v49)
- Modify: `platform/api/clue_api/agent_registry_wiring.py:105-113` (`C6_ACTIVE_PROFILE_VERSIONS`), `platform/api/clue_api/conversation_turns.py` / wherever `PROJECT_CONVERSATION_AGENT_PROFILE_ID` is defined (grep it; set `"head-of-abm@v50"`), `tests/agents/test_catalog.py` (the two address lists), `tests/api/test_agent_registry_wiring.py` (the `v49`/`v26` assertions and the measured manifest digest)
- Test: the two files above

**Interfaces:**
- Consumes: `build_toolbelt(storage=None, gateway=None).descriptor(name, version).input_schema_sha256 / .output_schema_sha256`.

- [ ] **Step 1: Measure the moved digests**

```bash
.venv/bin/python - <<'EOF'
from clue_api.toolbelt_wiring import build_toolbelt
belt = build_toolbelt(storage=None, gateway=None)
for name in ("read_project_accounts", "read_account_research", "read_discovery_run"):
    d = belt.descriptor(name, "1")
    print(name, d.input_schema_sha256, d.output_schema_sha256)
EOF
```

Expected: `read_account_research` input and output digests differ from v26's front matter; `read_discovery_run` output differs; `read_project_accounts` unchanged.

- [ ] **Step 2: Create skill v27**

Copy `v26/SKILL.md` to `v27/SKILL.md`. In the front matter, replace the three digest pairs with Step 1's values. Replace §7c with exactly this text (founder-reviewed with this plan):

```markdown
## 7c. Read before you speak about accounts

- **How many accounts, which are researched, what joined when:** `read_project_accounts`. `status.md` carries the summary; this read is the list.
- **What research found about one account:** `read_account_research`. Read `section: "overview"` first. The overview is written the first time someone opens the account's page, so a researched account can still answer `overview_not_written`; that is not a failure. Then read `section: "claims"`.
- **Claims come in pages.** A page ends with `next_offset`. When it is not null, read again with `offset: next_offset` before you summarize; a count or a "we found nothing about X" stated from one page is wrong. To narrow, pass `field_prefix` as one of the families the read returned in `prefixes` (for example `account.resonance`, `core`). Never invent a prefix.
- **What discovery found:** `read_discovery_run`.

Read accounts one at a time, in the order the human named them. A read costs nothing and is never a launch. Quote a fact only with a claim behind it; say when a field is empty. Never state a fact about an account from memory of an earlier thread.
```

Measure the `summary:` line of the front matter stays ≤ 512 characters (it does not change).

- [ ] **Step 3: Create profile v50**

Copy `v49/profile.yaml` to `v50/profile.yaml`; set `skills[0].version: v27`; prepend a header comment:

```yaml
# v50 (read-tool hotfix, 2026-09-13): v49 with the three reads' repaired contracts —
# `read_account_research` pages its claims (`offset`/`next_offset`), names the account's claim
# families (`prefixes`) and fits the governed receipt; `read_discovery_run` accepts the schema's
# own `pass` on input so its result passes the runner's validation. Skill pin moved v26→v27 (§7c:
# overviews render on first page view; read pages to the end; never invent a prefix). Nothing
# else moves. Digests read off the live descriptors.
```

- [ ] **Step 4: Point the registry at v50 and update the tests**

`agent_registry_wiring.py`: add the v50 comment beside the v49 one and set `AgentRole.HEAD_OF_ABM: "v50"`. Find and set `PROJECT_CONVERSATION_AGENT_PROFILE_ID` to `"head-of-abm@v50"` (grep: `PROJECT_CONVERSATION_AGENT_PROFILE_ID =`). In `tests/agents/test_catalog.py` add `"skill:stage0-interview@v27"` and `"profile:head-of-abm@v50"` to the sorted address lists. In `tests/api/test_agent_registry_wiring.py` change the `v49` and `v26` assertions to `v50`/`v27`, then run once to read the new `aggregate_sha256` from the failure and write it into `expected_manifests`.

Run: `.venv/bin/pytest tests/agents/test_catalog.py tests/api/test_agent_registry_wiring.py tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py tests/api/test_recipe_contracts.py tests/api/test_c8_trial_surface.py -p no:cacheprovider -q`
Expected: PASS except the pre-existing red `test_design_profile_resolves…` (grok vs terra), which is not this plan's.

- [ ] **Step 5: Commit**

```bash
git add platform/agents/catalog/skills/stage0-interview/v27 platform/agents/catalog/profiles/head-of-abm/v50 platform/api/clue_api/agent_registry_wiring.py platform/api/clue_api/conversation_turns.py tests/agents/test_catalog.py tests/api/test_agent_registry_wiring.py
git commit -m "feat(head-of-abm): v50 pins skill v27 — the repaired read contracts, paged claims, and §7c reads to the end"
```

---

### Task 6: Prove it on the stack

**Files:**
- Modify: `_memory/2026-09-13-live-walk-findings-and-workspace-reorg.md` (a "Hotfix proven" section)

- [ ] **Step 1: Gates**

```bash
.venv/bin/ruff format --check platform tests && .venv/bin/ruff check platform tests
.venv/bin/lint-imports
.venv/bin/pytest tests/api/test_arv2_read_tools.py tests/agents/test_governed_tool_feedback.py tests/agents/test_catalog.py tests/api/test_agent_registry_wiring.py -p no:cacheprovider -q
set -a; source .env; set +a; .venv/bin/pytest tests/arv2/test_read_tools_db.py --ignore-glob='*_live.py' -p no:cacheprovider -q
```

- [ ] **Step 2: Restart the lane stack on the new code**

```bash
./scripts/dev_stack_san_salvador.sh down > /tmp/san-salvador_down.log 2>&1
./scripts/dev_stack_san_salvador.sh up > /tmp/san-salvador_up.log 2>&1
./scripts/dev_stack_san_salvador.sh status
```

Confirm the workers loaded v50: `grep -h 'profile_version' /tmp/san-salvador_fleet_worker_*.log | tail -2`.

- [ ] **Step 3: The founder re-asks the live question**

In a new thread on the same project: "Can you tell me what was researched about Arthur Direct Care?". Expected: one `read_account_research` (overview) → `overview_not_written` refusal, then claims pages until `next_offset` is null, then an answer citing claims; the turn completes. Then the discovery question from the walk: `read_discovery_run` completes.

```sql
SELECT n.tool_name, count(*) FROM execution_node n
 WHERE n.kind='tool' AND n.tool_name IN ('read_account_research','read_discovery_run')
   AND n.created_at > now() - interval '1 hour' GROUP BY 1;
```

- [ ] **Step 4: Record and commit**

Append the transcript summary, the SQL output and any refusal to the memory note; commit with `docs(arv2): read-tools hotfix proven on the lane stack`.

---

## Self-review

- **Spec coverage:** §1's four tool failures → Tasks 1–3; W10 → Task 4; the grant → Task 5; live proof → Task 6. The fifth cause (overviews render lazily) is a product decision left open in the spec and is *documented* to the model in §7c rather than changed here. ✔
- **Placeholders:** none; the one `pass` in Task 2 Step 3 is replaced by the sentence that follows it. ✔
- **Type consistency:** `AccountResearch` gains `offset`, `next_offset`, `prefixes` in Task 2 and `prefixes` is filled in Task 3; the tool output mirrors all three; `_account_claims` returns a 4-tuple after Task 2 and a 5-tuple after Task 3 (Task 3 changes the unpacking in `read_account_research`). ✔
