# ARV2 R2 follow-ups (before R3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five small defects the R2-close re-run left in the account agent's write path and deep call, so the R3 person agent inherits the fixes rather than the defects.

**Architecture:** Five independent, small changes inside the existing ARV2 lane — no new tables, no new tools, no new machinery. (1) The agent sees each field's registered shape when it writes and gets the expected shape back when a value misses it; null optional keys are dropped on the agent's write path the way the mapper already does. (2) The "already established" block the agent pastes into the deep call is compacted and capped. (3) The deep call's evidence law asks for one assertion per sentence, quote first. (4) `read_media_feeds` takes alternate URLs and falls through when a source fails to load. (5) The AI Ark headquarters mapper emits `region` and, when the record carries it, `country_code`.

**Tech Stack:** Python 3.12, pydantic v2, LangChain `StructuredTool`, pytest; the ARV2 lane under `platform/api/clue_api/arv2/`; the arv2-account catalog under `platform/agents/catalog/entity-research/arv2-account/v1/`.

**Spec:** the follow-up list in `.context/arv2-r2-acceptance/rerun/before-after.md` §"Follow-ups", ratified by the founder 2026-09-09, plus the Exa evaluation `.context/arv2-exa-experiment/evaluation-claims-mode.md` §"Verdict" for item 3. Evidence for each defect: `.context/arv2-r2-acceptance/rerun/after/schema-invalid.txt` (37 rows), the deep-call request bodies in `.context/arv2-exa-experiment/request-zafran-report-mode.json` (34k-char query), `.context/arv2-r2-acceptance/rerun/after/receipts.txt` (media gaps).

## Global Constraints

- **No re-run of the two accounts in this plan** (founder ruling 2026-09-09): measurement folds into R3's acceptance run. Every task is proven by offline tests only.
- **Offline suites only, never with real keys sourced:** `uv run pytest tests/arv2 --ignore-glob='*_live.py' -p no:cacheprovider -q`. Do not `source .env` before running tests. Do not run `make check`.
- **Gates per task:** `uv run ruff format --check <files>` and `uv run ruff check <files>`; `uv run lint-imports` once at the end (import-linter rule 4b forbids the lane importing `clue_gateway.agent_model`; nothing here should touch that).
- **The catalog's `profile.md` is sha-pinned (the launch authorization pin) — do not edit it.** `manual.md` may change (Task 4). No catalog version bump is needed for these edits; `tests/arv2/test_account_research_catalog.py::test_five_files_exist_and_the_profile_sha_is_the_file_digest` must stay green.
- **Never `git stash`** (shared stash stack); never push; no AI attribution in commit messages; commit per task.
- **Failure law** (Appendix A): tools never raise into the graph; every new failure path is a `RefusalError` with a code the manual names, or a returned result.
- **Nothing decides meaning in code that the field does not declare** (the `coerce_scalar` rule): drop-null and shape hints read the registered `value_schema` only; no name→code tables, no guessed values.
- Test helpers already exist and are reused, never duplicated: `tests/arv2/test_account_research_tools.py::_runtime/_call/_claim_input/CATALOG/SCOPE/FakeWriter/FakeClients`, `tests/arv2/test_account_research_claims.py::CATALOG/SCOPE`.

---

### Task 1: The agent sees the field's shape at write time, and null optional keys are dropped

**Why:** 37 of the re-run's claims carry `schema_valid=false`; none are the shapes the close fixed. 18 are strings or lists written into bare-object fields, 16 are objects with the agent's own keys where the field names required ones, 2 are `"name": null` on a vacant committee seat, 1 is a persona outside the enum. The catalog the agent reads renders `key — description` and nothing about shape; `write_claims` returns `schema_valid: false` with no hint of what shape was expected; and `agent_claims` does no null-dropping while the mapper path (`_without_nones`) does.

**Files:**
- Modify: `platform/api/clue_api/arv2/structuring_client.py` — add `schema_hint()`, extend `catalog_menu_text()` (lines 172–191).
- Modify: `platform/api/clue_api/arv2/account_research_claims.py` — `agent_claims()` (lines 916–953) drops null optional keys on object-shaped fields; add `_required_keys()` beside `_declared_type()` (line 731).
- Modify: `platform/api/clue_api/arv2/account_research_tools.py` — `_receipt_json()` (lines 497–507) gains the catalog and reports `expected_shape` when the marker says the value missed; update its callers (`grep -n "_receipt_json(" platform/api/clue_api/arv2/account_research_tools.py`).
- Test: `tests/arv2/test_structuring_client.py`, `tests/arv2/test_account_research_claims.py`, `tests/arv2/test_account_research_tools.py`.

**Interfaces:**
- Produces: `structuring_client.schema_hint(schema: Mapping[str, object] | None) -> str` (pure; used by the menu and the receipt).
- Produces: `account_research_claims._required_keys(field_key: str, catalog: FieldCatalog) -> tuple[str, ...]` (pure).
- Changes: `account_research_tools._receipt_json(receipt: WriteReceipt, draft: ClaimDraft, catalog: FieldCatalog) -> dict[str, Any]` — third positional argument added.
- The `write_claims` result gains, per written row whose `markers.schema_valid is False`, two keys: `expected_shape: str` and `hint: str`.
- New marker on agent drafts: `dropped_null_keys: list[str]` (only when something was dropped).

- [ ] **Step 1: Write the failing tests for `schema_hint` and the menu**

Append to `tests/arv2/test_structuring_client.py` (import `schema_hint`, `catalog_menu_text`, `FieldCatalog`, `FieldSpec` from `clue_api.arv2.structuring_client`; keep the file's existing import block style):

```python
def test_schema_hint_renders_scalars_enums_objects_and_arrays_compactly() -> None:
    assert schema_hint(None) == "any"
    assert schema_hint({"type": "string"}) == "string"
    assert schema_hint({"type": "integer"}) == "integer"
    assert (
        schema_hint({"type": "string", "enum": ["champion", "blocker"]}) == "one of champion | blocker"
    )
    assert schema_hint({"type": "object"}) == "object"
    assert schema_hint(
        {
            "type": "object",
            "required": ["raw"],
            "properties": {"raw": {"type": "string"}, "city": {"type": "string"}},
        }
    ) == "object{raw: string, city?: string}"
    assert schema_hint(
        {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["frustration"],
                "properties": {"frustration": {"type": "string"}, "summary": {"type": "string"}},
            },
        }
    ) == "array<object{frustration: string, summary?: string}>"


def test_catalog_menu_text_shows_the_shape_beside_every_field_that_declares_one() -> None:
    catalog = FieldCatalog(
        account=(
            FieldSpec("account.gtm_tooling_stack", "GTM tools present and absent."),
            FieldSpec(
                "account.total_funding",
                "Total raised.",
                {
                    "type": "object",
                    "required": ["amount_usd", "estimate_kind"],
                    "properties": {
                        "amount_usd": {"type": "number"},
                        "estimate_kind": {
                            "type": "string",
                            "enum": ["reported", "provider_estimate", "third_party_estimate"],
                        },
                    },
                },
            ),
        )
    )
    menu = catalog_menu_text(catalog)
    assert "  account.gtm_tooling_stack — GTM tools present and absent.\n" in menu + "\n"
    assert (
        "  account.total_funding — Total raised. [shape: object{amount_usd: number, "
        "estimate_kind: one of reported | provider_estimate | third_party_estimate}]"
    ) in menu
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/arv2/test_structuring_client.py -k "schema_hint or menu_text_shows_the_shape" -q -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'schema_hint'`.

- [ ] **Step 3: Implement `schema_hint` and extend the menu**

In `platform/api/clue_api/arv2/structuring_client.py`, directly above `catalog_menu_text`:

```python
def schema_hint(schema: Mapping[str, object] | None) -> str:
    """One line of the shape a field's ``value_schema`` declares, for a model to read.

    ``object{raw: string, city?: string}`` — required keys bare, optional keys marked ``?``;
    ``array<…>`` for lists; ``one of a | b`` for enums; the bare JSON type otherwise. This is
    rendering, not validation: :func:`check_value_schema` decides; this only says what it will
    decide against, in fewer characters than the schema itself. ``None`` (no schema) is ``any``.
    """
    if not schema:
        return "any"
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return "one of " + " | ".join(str(value) for value in enum)
    declared = schema.get("type")
    if declared == "object":
        properties = schema.get("properties")
        if not isinstance(properties, Mapping) or not properties:
            return "object"
        required = schema.get("required")
        required_keys = {str(key) for key in required} if isinstance(required, list) else set()
        parts = [
            f"{name}{'' if name in required_keys else '?'}: "
            f"{schema_hint(sub if isinstance(sub, Mapping) else None)}"
            for name, sub in properties.items()
        ]
        return "object{" + ", ".join(parts) + "}"
    if declared == "array":
        items = schema.get("items")
        return f"array<{schema_hint(items if isinstance(items, Mapping) else None)}>"
    return str(declared) if isinstance(declared, str) else "any"
```

In `catalog_menu_text`, replace the line-rendering expression so a field with a schema shows it:

```python
    def line(spec: FieldSpec) -> str:
        if spec.value_schema is None:
            return f"  {spec.key} — {spec.description}"
        return f"  {spec.key} — {spec.description} [shape: {schema_hint(spec.value_schema)}]"

    blocks = [
        "\n".join([heading, *(line(spec) for spec in specs)]) for heading, specs in sections
    ]
```

Update the `catalog_menu_text` docstring: the menu now names the shape because the R2 re-run's 37 schema-invalid claims were all written by a model that had never seen one.

- [ ] **Step 4: Run the two tests; then the whole structuring suite**

Run: `uv run pytest tests/arv2/test_structuring_client.py -q -p no:cacheprovider`
Expected: all PASS. If an existing test asserted the old exact menu text, update its expectation to include ` [shape: …]` for fields that declare a schema — the change is deliberate.

- [ ] **Step 5: Write the failing tests for null-dropping on the agent path**

Append to `tests/arv2/test_account_research_claims.py` (it already imports `agent_claims`? if not, add it; `ClaimInput` is in `clue_api.arv2.account_research_claims`; `CATALOG` there carries `core.employee_range` with `required: ["label"]`):

```python
def test_agent_claims_drop_null_optional_keys_on_an_object_field_and_keep_required_ones() -> None:
    items = [
        ClaimInput(
            field_key="core.employee_range",
            value={"label": "51-200", "min": None, "max": 200},
            evidence_span="51-200 employees",
            source_url="https://example.test/about",
            priority=2,
        ),
        ClaimInput(
            field_key="core.employee_range",
            value={"label": None, "min": 51, "max": 200},
            evidence_span="51-200 employees",
            source_url="https://example.test/about",
            priority=2,
        ),
    ]
    first, second = agent_claims(items, SCOPE, catalog=CATALOG)
    assert first.value_json == {"label": "51-200", "max": 200}
    assert first.markers["dropped_null_keys"] == ["min"]
    # A required key nothing answered stays, so the schema marker can say the value does not fit.
    assert second.value_json == {"label": None, "min": 51, "max": 200}
    assert "dropped_null_keys" not in second.markers


def test_agent_claims_leave_non_object_values_and_unschemad_fields_alone() -> None:
    items = [
        ClaimInput(
            field_key="core.industries_all",
            value=["saas", None],
            evidence_span="saas",
            source_url="https://example.test/about",
            priority=3,
        ),
    ]
    (draft,) = agent_claims(items, SCOPE, catalog=CATALOG)
    assert draft.value_json == ["saas", None]
    assert "dropped_null_keys" not in draft.markers
```

- [ ] **Step 6: Run them to verify they fail**

Run: `uv run pytest tests/arv2/test_account_research_claims.py -k "drop_null or leave_non_object" -q -p no:cacheprovider`
Expected: FAIL — `first.value_json` still carries `"min": None`.

- [ ] **Step 7: Implement `_required_keys` and the drop in `agent_claims`**

Beside `_declared_type` in `account_research_claims.py`:

```python
def _required_keys(field_key: str, catalog: FieldCatalog) -> tuple[str, ...] | None:
    """The required keys of an object-typed field, or ``None`` when the field is not an object."""
    spec = catalog.spec(field_key)
    schema = spec.value_schema if spec else None
    if not schema or schema.get("type") != "object":
        return None
    required = schema.get("required")
    return tuple(str(key) for key in required) if isinstance(required, list) else ()
```

In `agent_claims`, after `value, coercion = _coerced(field_key, item.value, catalog)`:

```python
        markers: dict[str, JsonValue] = dict(coercion)
        required = _required_keys(field_key, catalog)
        if required is not None and isinstance(value, Mapping):
            # The mapper path already drops the optional keys a record did not answer
            # (``_without_nones``); the agent path did not, and the re-run's two vacant seats
            # landed ``schema_valid=false`` on ``"name": null`` alone. Same rule, same helper:
            # absent is not null, and a required key stays so the marker can say it is missing.
            kept = _without_nones(value, keep=required)
            dropped = [key for key in value if key not in kept]
            if dropped:
                markers["dropped_null_keys"] = dropped
            value = kept
```

(`markers` was previously initialised on the next line as `dict(coercion)`; fold it into this block so it is defined once.)

- [ ] **Step 8: Run the claims suite**

Run: `uv run pytest tests/arv2/test_account_research_claims.py -q -p no:cacheprovider`
Expected: all PASS.

- [ ] **Step 9: Write the failing tool test for `expected_shape`**

In `tests/arv2/test_account_research_tools.py`, extend `FakeWriter` so a test can make the gate report a schema miss (the real `LenientClaimWriter` sets `markers["schema_valid"] = False` on `ValueSchemaError`):

```python
        #: field keys this writer stores but marks ``schema_valid=False``, as the real gate does
        #: when the value misses the field's registered schema.
        self.schema_invalid: set[str] = set()
```

and in `FakeWriter.write`, before building the receipt:

```python
        markers = dict(draft.markers)
        if draft.field_key in self.schema_invalid:
            markers["schema_valid"] = False
        self.drafts.append(draft)
        return WriteReceipt(
            claim_id=ClaimId(uuid4()),
            field_key=draft.field_key,
            markers=markers,
            registered_field=False,
        )
```

Then add, after `test_write_claims_refuses_a_named_committee_candidate_with_no_confirming_url`:

```python
def test_write_claims_reports_the_expected_shape_when_a_value_missed_its_schema() -> None:
    """The model wrote a string into an object field; the receipt says what shape was wanted."""
    runtime, _, writer, _ = _runtime()
    writer.schema_invalid = {"core.hq_location"}
    claim = _claim_input(0)
    claim["field_key"] = "core.hq_location"
    claim["value"] = "New York, NY"

    result = _call(runtime, "write_claims", claims=[claim])

    (row,) = result["written"]
    assert row["markers"]["schema_valid"] is False
    assert row["expected_shape"] == "object{raw: string, city?: string}"
    assert row["hint"].startswith("rewrite the value in this shape and write it again with corrects_claim_id=")
    assert row["claim_id"] in row["hint"]


def test_write_claims_receipts_carry_no_shape_when_the_value_fit() -> None:
    runtime, _, _, _ = _runtime()
    result = _call(runtime, "write_claims", claims=[_claim_input(0)])
    (row,) = result["written"]
    assert "expected_shape" not in row and "hint" not in row
```

- [ ] **Step 10: Run them to verify they fail**

Run: `uv run pytest tests/arv2/test_account_research_tools.py -k "expected_shape or no_shape_when" -q -p no:cacheprovider`
Expected: FAIL — `KeyError: 'expected_shape'`.

- [ ] **Step 11: Implement the receipt**

In `account_research_tools.py`, import `schema_hint` from `clue_api.arv2.structuring_client` (the module already imports `FieldCatalog` from there) and change `_receipt_json`:

```python
def _receipt_json(receipt: WriteReceipt, draft: ClaimDraft, catalog: FieldCatalog) -> dict[str, Any]:
    row: dict[str, Any] = {
        "claim_id": str(receipt.claim_id),
        "field_key": receipt.field_key,
        "value": draft.value_json,
        "quote": draft.evidence_span,
        "url": draft.source_url,
        "priority": draft.signal_priority,
        "outreach_safe": draft.outreach_safe,
        "markers": receipt.markers,
    }
    if receipt.markers.get("schema_valid") is False:
        # The claim is stored and visible with its marker (founder ruling 2026-09-08); the receipt
        # is the one place the model learns, in the same turn, what shape the field wanted.
        spec = catalog.spec(receipt.field_key)
        row["expected_shape"] = schema_hint(spec.value_schema if spec else None)
        row["hint"] = (
            "rewrite the value in this shape and write it again with "
            f"corrects_claim_id={receipt.claim_id}"
        )
    return row
```

Update every caller to pass `runtime.catalog` (`grep -n "_receipt_json(" platform/api/clue_api/arv2/account_research_tools.py` — `_write_claims` and any structuring/finalize caller).

- [ ] **Step 12: Run the tools suite, then lint**

Run: `uv run pytest tests/arv2/test_account_research_tools.py -q -p no:cacheprovider`
Expected: all PASS.
Run: `uv run ruff format --check platform/api/clue_api/arv2 tests/arv2 && uv run ruff check platform/api/clue_api/arv2 tests/arv2`
Expected: clean.

- [ ] **Step 13: Tell the agent, in its skill, what the receipt now says**

In `platform/agents/catalog/entity-research/arv2-account/v1/dossier.md`, §"Structuring, and the second pass", item 3 (the paragraph beginning "`structure_material` **writes** the claims…"), append one sentence at its end:

```
   The catalog names each field's shape (`[shape: …]`), and a `write_claims` receipt whose
   `schema_valid` is false carries `expected_shape` and a `hint` — rewrite the value in that shape
   and write it again with `corrects_claim_id`; never leave a value you can reshape.
```

Run: `uv run pytest tests/arv2/test_account_research_catalog.py -q -p no:cacheprovider`
Expected: PASS (only `profile.md` is sha-pinned; the skill digests are read at load).

- [ ] **Step 14: Commit**

```bash
git add platform/api/clue_api/arv2/structuring_client.py platform/api/clue_api/arv2/account_research_claims.py platform/api/clue_api/arv2/account_research_tools.py platform/agents/catalog/entity-research/arv2-account/v1/dossier.md tests/arv2/test_structuring_client.py tests/arv2/test_account_research_claims.py tests/arv2/test_account_research_tools.py
git commit -m "arv2 r2 follow-ups: the agent sees each field's shape in the catalog and in a schema-miss receipt; null optional keys are dropped on the agent write path

The R2-close re-run left 37 schema_valid=false claims, all written by the agent through write_claims against a catalog that showed key and description but never shape. The menu now renders [shape: ...] beside every field that declares a schema, a receipt whose value missed carries expected_shape and a corrects_claim_id hint, and agent_claims drops null optional keys on object fields the way the mapper path already did (two vacant seats had landed on name: null alone)."
```

---

### Task 2: Compact and cap the "already established" block the deep call carries

**Why:** Zafran's deep-call query was 34,558 characters against Probook's 2,887. The agent appends `scope.already_established` verbatim to the deep query; that block is up to 60 lines of `field_key: <python repr of value_json> (url)`, and a single AI Ark record or open-requisitions list can be thousands of characters. The deep call's budget then goes to re-reading what the agent already has.

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` — `_already_established()` (lines 532–548) and `_ESTABLISHED_LINE_CAP` (line 111); add module-level `format_established(claims) -> str`.
- Modify: `platform/api/clue_api/arv2/account_research_tools.py` — `_research_deep()` (lines ~1000–1040); add `_DEEP_ESTABLISHED_MAX_CHARS` beside the other `_…_CHARS` constants (lines 152–163) and `_clip_lines()`.
- Test: `tests/arv2/test_account_research_driver.py`, `tests/arv2/test_account_research_tools.py`.

**Interfaces:**
- Produces: `account_research_driver.format_established(claims: Sequence[Claim]) -> str` (pure; the method calls it).
- Produces: `account_research_tools._clip_lines(block: str, max_chars: int) -> str` (pure).
- Constants: `account_research_driver._ESTABLISHED_VALUE_CHARS = 240`; `account_research_tools._DEEP_ESTABLISHED_MAX_CHARS = 6000`.

- [ ] **Step 1: Write the failing driver test**

Append to `tests/arv2/test_account_research_driver.py`. Build `Claim` objects the way `tests/arv2/test_account_research_tools.py::_claim` does (copy that helper's constructor call if this file has none — read it first; it sets `entity_id/entity_type/field_key/value_json/source_url/source_key/source_tier/extraction_method/evidence_span/…`):

```python
def test_format_established_writes_compact_json_values_capped_per_line() -> None:
    long_list = [{"title": f"Role {i}", "url": f"https://jobs.test/{i}"} for i in range(40)]
    claims = [
        _claim("account.open_requisitions", value=long_list, url="https://jobs.test"),
        _claim("core.founded_year", value=2022, url=None, source_key="ai_ark:company"),
    ]
    text = format_established(claims)
    lines = text.split("\n")
    assert len(lines) == 2
    assert lines[0].startswith('- account.open_requisitions: [{"title": "Role 0"')
    assert lines[0].endswith("… (https://jobs.test)")
    assert len(lines[0]) <= 240 + len("- account.open_requisitions: ") + len("… (https://jobs.test)")
    assert lines[1] == "- core.founded_year: 2022 (ai_ark:company)"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/arv2/test_account_research_driver.py -k format_established -q -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'format_established'`.

- [ ] **Step 3: Implement `format_established`**

In `account_research_driver.py`, beside `_ESTABLISHED_LINE_CAP = 60`:

```python
#: Characters of one claim's value the established block shows. The re-run's Zafran deep query
#: was 34k characters because a single AI Ark record or requisition list rode in whole; a line
#: exists to tell the agent *that* a field is known and roughly what it says, not to be the value.
_ESTABLISHED_VALUE_CHARS = 240


def format_established(claims: Sequence[Claim]) -> str:
    """The "already established" block: one compact line per live claim, newest first.

    Values are compact JSON (not Python ``repr``), cut at :data:`_ESTABLISHED_VALUE_CHARS` with
    an ellipsis; the source is the URL, else the source key. The full value is one
    ``read_account_state`` call away, and that is where a model that needs it should look.
    """
    lines = []
    for claim in claims[:_ESTABLISHED_LINE_CAP]:
        value = json.dumps(claim.value_json, ensure_ascii=False, default=str, separators=(", ", ": "))
        if len(value) > _ESTABLISHED_VALUE_CHARS:
            value = value[:_ESTABLISHED_VALUE_CHARS] + "…"
        source = claim.source_url or claim.source_key or "no source"
        lines.append(f"- {claim.field_key}: {value} ({source})")
    return "\n".join(lines)
```

and make `_already_established` end with `return format_established(claims)` (delete its inline list comprehension). Add `import json` and `from collections.abc import Sequence` if not already imported; `Claim` is already imported (check the module's imports).

- [ ] **Step 4: Run the driver suite**

Run: `uv run pytest tests/arv2/test_account_research_driver.py -q -p no:cacheprovider`
Expected: all PASS.

- [ ] **Step 5: Write the failing tool test for the deep-call clip**

In `tests/arv2/test_account_research_tools.py`, after `test_research_deep_refuses_only_when_the_report_is_empty` (read `test_research_deep_returns_the_report_and_the_lock` first to see how the fake Exa client records the `query` it was given — reuse that attribute):

```python
def test_research_deep_clips_the_already_established_block_and_says_where_the_rest_is() -> None:
    lines = "\n".join(f"- account.field_{i}: {'x' * 90} (https://s.test/{i})" for i in range(200))
    scope = replace(SCOPE, already_established=lines)
    runtime, clients, _, _ = _runtime(scope)

    _call(runtime, "research_deep", charter=CHARTER)

    query = clients.exa_client.deep_calls[-1]["query"]  # adjust to the fake's real attribute
    established = query.split("ALREADY ESTABLISHED", 1)[1]
    assert len(established) <= 6000 + 200, "whole lines up to the cap, plus the omission note"
    assert "lines omitted" in established
    assert 'read_account_state(section="already_established")' in established
    assert "- account.field_0:" in established and "- account.field_199:" not in established


def test_research_deep_passes_a_short_established_block_through_untouched() -> None:
    runtime, clients, _, _ = _runtime()
    _call(runtime, "research_deep", charter=CHARTER)
    query = clients.exa_client.deep_calls[-1]["query"]
    assert query.endswith("ALREADY ESTABLISHED (do not re-derive; find what is NOT here)\nFounded 2021.")
```

(`replace` is `dataclasses.replace`; `JobScope` is a frozen dataclass — confirm at `account_research_claims.py:~105`.)

- [ ] **Step 6: Run them to verify they fail**

Run: `uv run pytest tests/arv2/test_account_research_tools.py -k "clips_the_already_established or established_block_through" -q -p no:cacheprovider`
Expected: the first FAILS (`"lines omitted" not in established`); the second PASSES already (it pins current behaviour).

- [ ] **Step 7: Implement the clip**

In `account_research_tools.py`, beside `_VERIFY_TEXT_MAX_CHARS`:

```python
#: Characters of the "already established" block one deep call carries. The block tells Exa what
#: not to re-derive; past a few thousand characters it is the query, and the re-run's Zafran call
#: spent its budget re-reading an AI Ark record instead of researching (34k-char query vs 2.9k).
_DEEP_ESTABLISHED_MAX_CHARS = 6000


def _clip_lines(block: str, max_chars: int) -> str:
    """Whole lines from the top of ``block`` up to ``max_chars``, then one line saying how many
    were left out and where they are. A block within the cap is returned unchanged."""
    if len(block) <= max_chars:
        return block
    kept: list[str] = []
    used = 0
    lines = block.split("\n")
    for line in lines:
        if used + len(line) + 1 > max_chars:
            break
        kept.append(line)
        used += len(line) + 1
    omitted = len(lines) - len(kept)
    kept.append(
        f"… ({omitted} lines omitted; read_account_state(section=\"already_established\") "
        "has them all)"
    )
    return "\n".join(kept)
```

In `_research_deep`, replace `(scope.already_established or "(nothing yet)")` with
`_clip_lines(scope.already_established or "(nothing yet)", _DEEP_ESTABLISHED_MAX_CHARS)`.

- [ ] **Step 8: Run the tools suite and lint**

Run: `uv run pytest tests/arv2/test_account_research_tools.py -q -p no:cacheprovider && uv run ruff format --check platform/api/clue_api/arv2 tests/arv2 && uv run ruff check platform/api/clue_api/arv2 tests/arv2`
Expected: all PASS, lint clean.

- [ ] **Step 9: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_driver.py platform/api/clue_api/arv2/account_research_tools.py tests/arv2/test_account_research_driver.py tests/arv2/test_account_research_tools.py
git commit -m "arv2 r2 follow-ups: the already-established block is compact JSON capped per line, and the deep call carries at most 6k chars of it

Zafran's deep-call query was 34k characters against Probook's 2.9k because whole AI Ark records and requisition lists rode in as Python reprs. Each line now shows at most 240 chars of compact JSON, and research_deep clips the block to whole lines within 6,000 chars with a note saying how many were omitted and that read_account_state has them."
```

---

### Task 3: The deep call's evidence law asks for one assertion per sentence, quote first

**Why:** The Exa claims-mode experiment (`.context/arv2-exa-experiment/evaluation-claims-mode.md`) showed a structured schema makes quotes 94–95% verbatim but collapses coverage; its verdict was to keep the report string and instead ask the report for one assertion per sentence with the quote first, so the structuring pass gets cleaner input without losing budget to shape. This is the deep call's **system prompt** (`EVIDENCE_RULES`), not the agent's skill.

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_tools.py` — `EVIDENCE_RULES` (lines 178–190).
- Test: `tests/arv2/test_account_research_tools.py`.

**Interfaces:** none new; `EVIDENCE_RULES` remains a module constant.

- [ ] **Step 1: Write the failing test**

After the `research_deep` tests in `tests/arv2/test_account_research_tools.py`:

```python
def test_the_deep_call_evidence_law_asks_for_one_assertion_per_sentence_quote_first() -> None:
    runtime, clients, _, _ = _runtime()
    _call(runtime, "research_deep", charter=CHARTER)
    system_prompt = clients.exa_client.deep_calls[-1]["system_prompt"]  # the fake's attribute
    assert "One assertion per sentence" in system_prompt
    assert "the verbatim quote first, then the URL in parentheses" in system_prompt
    assert "A NOT FOUND item is its own sentence" in system_prompt
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/arv2/test_account_research_tools.py -k "one_assertion_per_sentence" -q -p no:cacheprovider`
Expected: FAIL — the substrings are not in the prompt.

- [ ] **Step 3: Add the two rules**

In `EVIDENCE_RULES`, append after the CONFIRMED/DENIED/UNRESOLVED bullet, keeping the existing indentation:

```python
  * One assertion per sentence: the verbatim quote first, then the URL in parentheses, then at
    most one clause of your own reading. A sentence never carries two facts, and a quote never
    supports more than the sentence it sits in.
  * A NOT FOUND item is its own sentence naming exactly what was looked for (the tool, the
    person, the number), so that absence is recorded as precisely as presence."""
```

Add a line to the constant's comment: the shape was chosen on the 2026-09-08 Exa experiment — a claims-shaped output schema lifted quote fidelity to 94–95% but cost two-thirds of the assertions; asking the *report* for quote-first sentences keeps the budget on coverage.

- [ ] **Step 4: Run the tools suite and lint**

Run: `uv run pytest tests/arv2/test_account_research_tools.py -q -p no:cacheprovider && uv run ruff format --check platform/api/clue_api/arv2/account_research_tools.py && uv run ruff check platform/api/clue_api/arv2/account_research_tools.py`
Expected: all PASS, lint clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_tools.py tests/arv2/test_account_research_tools.py
git commit -m "arv2 r2 follow-ups: the deep call's evidence law asks for one assertion per sentence, quote first, and a sentence per NOT FOUND item

Chosen on the 2026-09-08 Exa experiment: a claims-shaped output schema made quotes 94-95% verbatim but cut assertions to a third; asking the report string for quote-first single-fact sentences keeps the budget on coverage and gives the structuring pass cleaner spans."
```

---

### Task 4: `read_media_feeds` takes alternate URLs and falls through when a source will not load

**Why:** Two runs, zero media claims. Probook's YouTube watch page answered 429; Zafran's podcast feed did not resolve (`feed_not_found`). Both are external, but the tool gives up on the first URL: it takes one `feed_url` or one `youtube_url`, and a load failure is a refusal. The agent usually has more than one candidate (the podcast's other host, the YouTube upload of the same episode) and nowhere to put them.

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_tools.py` — `ReadMediaFeedsArgs` (lines 559–572), `_podcast_hop` (line 835), `_youtube_hop` (line 917), `_read_media_feeds` (lines 952–975+), and the `read_media_feeds` tool description (line ~1511).
- Modify: `platform/agents/catalog/entity-research/arv2-account/v1/manual.md` — the `feed_not_found` row (line 33) and the `read_media_feeds` tool row (line 58).
- Test: `tests/arv2/test_account_research_tools.py`.

**Interfaces:**
- `ReadMediaFeedsArgs` gains `alternate_urls: list[HttpUrl] = Field(default_factory=list, max_length=4)`.
- `_podcast_hop(runtime, args, feed_url: str)` and `_youtube_hop(runtime, args, watch_url: str)` take the URL explicitly (they no longer read `args.feed_url` / `args.youtube_url`).
- The tool result gains `source_attempts: list[{"url": str, "error": str}]` — the sources that failed to load before one succeeded (empty when the first loaded).
- A `feed_not_found` refusal's message names every URL tried with its error.

- [ ] **Step 1: Write the failing tests**

In `tests/arv2/test_account_research_tools.py`, in the `read_media_feeds` section (read `_stub_podcast` and `test_read_media_feeds_transcribes_a_short_episode_and_writes_the_index_claim` first; the tests monkeypatch `tools.fetch_feed`, and `MediaFetchError(url, status, raw_ref)` is importable from `clue_api.arv2.media_feeds_client`):

```python
def test_read_media_feeds_falls_through_to_an_alternate_when_the_first_source_will_not_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Probook's YouTube page answered 429 and the run had nowhere to try next."""
    _stub_podcast(monkeypatch, tmp_path)
    good_feed = "https://pod.test/feed"
    calls: list[str] = []
    real_fetch = tools.fetch_feed

    def fetch(url: str, caller: Any) -> Any:
        calls.append(url)
        if url == "https://dead.test/feed":
            raise MediaFetchError(url, 429, None)
        return real_fetch(url, caller)

    monkeypatch.setattr(tools, "fetch_feed", fetch)
    runtime, _, writer, _ = _runtime()

    result = _call(
        runtime,
        "read_media_feeds",
        person_name="George Eliadis",
        feed_url="https://dead.test/feed",
        alternate_urls=[good_feed],
        episode_title_contains="George",
    )

    assert "code" not in result, result
    assert calls == ["https://dead.test/feed", good_feed]
    assert result["source_attempts"] == [
        {"url": "https://dead.test/feed", "error": "https://dead.test/feed answered HTTP 429"}
    ]
    assert result["item"]["kind"] == "podcast"
    assert any(d.field_key == "account.media_layer_index" for d in writer.drafts)


def test_read_media_feeds_refuses_feed_not_found_naming_every_url_it_tried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fetch(url: str, caller: Any) -> Any:
        raise MediaFetchError(url, 404, None)

    monkeypatch.setattr(tools, "fetch_feed", fetch)
    runtime, _, writer, _ = _runtime()

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="George Eliadis",
        feed_url="https://a.test/feed",
        alternate_urls=["https://b.test/feed"],
    )

    assert refused["code"] == "feed_not_found"
    assert "https://a.test/feed" in refused["message"] and "https://b.test/feed" in refused["message"]
    assert writer.drafts == []


def test_read_media_feeds_does_not_fall_through_past_a_feed_that_loaded_but_had_no_episode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A feed that loaded and has no matching episode is an answer, not a load failure."""
    _stub_podcast(monkeypatch, tmp_path)
    runtime, _, _, _ = _runtime()
    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nobody",
        feed_url="https://pod.test/feed",
        alternate_urls=["https://never.test/feed"],
        episode_title_contains="no such episode",
    )
    assert refused["code"] == "episode_not_found"
```

The exact `MediaFetchError` message text in the first test must match `str(MediaFetchError(url, 429, None))` — read `media_feeds_client.py:123–137` and adjust the expected string to what `__str__` actually produces.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/arv2/test_account_research_tools.py -k "falls_through_to_an_alternate or naming_every_url or past_a_feed_that_loaded" -q -p no:cacheprovider`
Expected: the first two FAIL (`alternate_urls` is refused as an unknown argument → `invalid_arguments`); the third PASSES or fails on the unknown argument — either way it must pass after Step 3.

- [ ] **Step 3: Implement the fall-through**

`ReadMediaFeedsArgs`:

```python
class ReadMediaFeedsArgs(_Args):
    person_name: str = Field(min_length=2)
    person_role: str = ""
    feed_url: HttpUrl | None = None
    youtube_url: HttpUrl | None = None
    #: More places the same appearance may load from — the podcast's other feed host, the
    #: YouTube upload of the episode — tried in order only when the source before it would not
    #: load. Each is a feed or a watch URL, told apart by host. Two runs produced no media because
    #: one 429 and one dead feed were each the only URL the call carried.
    alternate_urls: list[HttpUrl] = Field(default_factory=list, max_length=4)
    episode_title_contains: str | None = None
    episode_number: int | None = None
    # (keep the existing _needs_one_source validator)
```

`_podcast_hop(runtime, args, feed_url: str)`: delete the line `feed_url = str(args.feed_url)`; `_youtube_hop(runtime, args, watch_url: str)`: delete `watch_url = str(args.youtube_url)`.

`_read_media_feeds`:

```python
async def _read_media_feeds(runtime: ToolRuntime, args: ReadMediaFeedsArgs) -> dict[str, Any]:
    # The primary first (feed before watch page when both are given: a transcript beats indexed
    # page words), then the alternates in the order the model gave them. A source that will not
    # LOAD hands over to the next; a source that loaded and answered (no matching episode, over
    # the ceiling, a walled host) is the answer, and is not second-guessed by trying another URL.
    candidates = [str(url) for url in (args.feed_url, args.youtube_url) if url is not None]
    candidates.extend(str(url) for url in args.alternate_urls)
    attempts: list[dict[str, str]] = []
    item: _MediaItem | None = None
    for url in candidates:
        hop = _youtube_hop(runtime, args, url) if is_youtube(url) else _podcast_hop(runtime, args, url)
        try:
            item = await runtime.call_provider("media", hop)
            break
        except MediaCeilingExceeded as ceiling:
            raise RefusalError("media_ceiling_reached", str(ceiling)) from ceiling
        except EnclosureTooLarge as oversized:
            raise RefusalError("enclosure_too_large", str(oversized)) from oversized
        except UnsupportedMediaHost as walled:
            raise RefusalError("native_video_rejected", str(walled)) from walled
        except (MediaFetchError, RawParseError) as unreachable:
            attempts.append({"url": url, "error": str(unreachable)})
    if item is None:
        raise RefusalError(
            "feed_not_found",
            "no source loaded: " + "; ".join(f"{a['url']} ({a['error']})" for a in attempts),
        )
    # … existing body: write the index claim, build the result dict …
    result = { … existing keys … }
    result["source_attempts"] = attempts
    return result
```

`is_youtube` is in `clue_api.arv2.media_feeds_client` — add it to the existing import from that module. Note `RefusalError("episode_not_found", …)` raised inside `_podcast_hop` is not caught by the loop and propagates as before.

Update the `read_media_feeds` tool description (line ~1511) to mention `alternate_urls`: "…give every other place the same appearance may load from as `alternate_urls` (another feed host, the YouTube upload); they are tried in order only if the source before them will not load."

- [ ] **Step 4: Update the manual**

`platform/agents/catalog/entity-research/arv2-account/v1/manual.md`:

Line 33, the `feed_not_found` row, replace the reaction cell with:
`Every URL given failed to load (the message names each with its error). If you have not yet passed alternates — the podcast's other feed host, the YouTube upload of the same episode — call once more with them in alternate_urls; otherwise media stays empty for this person; move on.`

Line 58, the tool row signature: `read_media_feeds(person_name, person_role, feed_url, youtube_url, alternate_urls, episode_title_contains, episode_number)`.

- [ ] **Step 5: Run the tools and catalog suites, then lint**

Run: `uv run pytest tests/arv2/test_account_research_tools.py tests/arv2/test_account_research_catalog.py -q -p no:cacheprovider && uv run ruff format --check platform/api/clue_api/arv2 tests/arv2 && uv run ruff check platform/api/clue_api/arv2 tests/arv2`
Expected: all PASS (the existing media tests still pass — they pass `feed_url` alone), lint clean.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_tools.py platform/agents/catalog/entity-research/arv2-account/v1/manual.md tests/arv2/test_account_research_tools.py
git commit -m "arv2 r2 follow-ups: read_media_feeds takes alternate_urls and falls through when a source will not load; feed_not_found names every URL tried

Two runs produced no media: Probook's watch page answered 429 and Zafran's feed did not resolve, and each was the only URL the call carried. Sources are now tried in order (feed before watch page, then the alternates); a source that loaded but answered (no episode, over the ceiling, a walled host) is still the answer and is not second-guessed. The result carries source_attempts."
```

---

### Task 5: The AI Ark headquarters shape carries `region` and, when present, `country_code`

**Why:** `core.hq_location` is registered as `object{raw, city?, region?, country?, country_code?}`. The mapper emits `raw`, `city`, `country` and drops the record's `location.headquarter.state`, which is the field's `region`. The answer key's HQ rows carry `region`, so the claim grades partial for a fact the record actually has.

**Scope note (honest):** the AI Ark record carries `country: "United States"` and no ISO code; the answer key holds `country: "US"`, `region: "NY"`. Emitting `region: "New York"` records what the provider said. No name→code table is added (the `coerce_scalar` rule: the mapper does not decide what a value means), so exact-match against the key's codes is a grader normalisation question, not this task's. `country_code` is emitted only when the record itself carries one.

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_claims.py` — `_hq_location()` (lines 334–358).
- Test: `tests/arv2/test_account_research_claims.py` (the assertion at lines 271–275) and its AI Ark fixture record (find where the test's `company` record's `location.headquarter` is defined — `grep -rn "raw_address" tests/arv2/` — and add `"state": "New York"` if absent).

**Interfaces:** none new; the `core.hq_location` value gains optional keys `region` / `country_code`.

- [ ] **Step 1: Update the test to the new shape (it will fail first)**

In `tests/arv2/test_account_research_claims.py`, make the fixture's `location.headquarter` carry `"state": "New York"` (and no `country_code`), then change the assertion at line 271:

```python
    assert drafts["core.hq_location"].value_json == {
        "raw": "New York, New York, United States",
        "city": "New York",
        "region": "New York",
        "country": "US",
    }
```

and add beneath it:

```python
def test_hq_location_emits_country_code_only_when_the_record_carries_one() -> None:
    assert _hq_location(
        {"raw_address": "Tel Aviv, Israel", "city": "Tel Aviv", "country": "Israel", "country_code": "IL"}
    ) == {"raw": "Tel Aviv, Israel", "city": "Tel Aviv", "country": "Israel", "country_code": "IL"}
    assert _hq_location({"raw_address": "Tel Aviv, Israel", "state": None}) == {"raw": "Tel Aviv, Israel"}
    assert _hq_location({"city": "Tel Aviv"}) is None
```

(`_hq_location` is private; import it directly — the file already imports private helpers from the module, check the import block.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/arv2/test_account_research_claims.py -k "hq_location or ai_ark_company_claims" -q -p no:cacheprovider`
Expected: FAIL — `"region"` missing from the value.

- [ ] **Step 3: Implement**

In `_hq_location`, replace the returned mapping and extend the docstring's second paragraph:

```python
    return _without_nones(
        {
            "raw": raw_address,
            "city": _dig(location, "city"),
            # The provider's ``state`` is the registry's ``region``; the record carries no ISO code
            # for either, so ``country_code`` appears only when the provider spelled one out —
            # never from a name→code table (the mapper does not decide what a value means).
            "region": _dig(location, "state"),
            "country": _dig(location, "country"),
            "country_code": _dig(location, "country_code"),
        },
        keep=("raw",),
    )
```

Docstring: "The provider answers ``continent/country/city/state/raw_address/position``; the registry requires ``raw`` and knows ``city``/``region``/``country``/``country_code``. ``state`` is ``region``."

- [ ] **Step 4: Run the claims suite and lint**

Run: `uv run pytest tests/arv2/test_account_research_claims.py -q -p no:cacheprovider && uv run ruff format --check platform/api/clue_api/arv2/account_research_claims.py tests/arv2/test_account_research_claims.py && uv run ruff check platform/api/clue_api/arv2/account_research_claims.py tests/arv2/test_account_research_claims.py`
Expected: all PASS, lint clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_claims.py tests/arv2/test_account_research_claims.py
git commit -m "arv2 r2 follow-ups: the AI Ark headquarters shape carries region (the record's state) and country_code when the record has one

The registry knows region and country_code; the mapper dropped the record's state, so every HQ claim graded partial for a fact the provider had answered. No name-to-code table: the mapper records what the provider said."
```

---

### Task 6: Whole-slice gates and the record

**Files:**
- Modify: `_memory/2026-09-08-arv2-r2-account-agent.md` — append a "R2 follow-ups DONE" section.
- Modify: `docs/superpowers/plans/2026-09-08-arv2-r2-close.md` — under Task 7's DONE note, one line pointing at this plan for the follow-ups.

- [ ] **Step 1: Run the offline ARV2 suite, lint, contracts**

Run:
```bash
uv run pytest tests/arv2 --ignore-glob='*_live.py' -p no:cacheprovider -q
uv run ruff format --check . && uv run ruff check .
uv run lint-imports
```
Expected: all green. If `tests/arv2` shows the two known base env-parity failures (`test_head_resource_map_is_exhaustive…`, `test_design_profile_resolves…` live under `tests/` not `tests/arv2`, so they should not appear); anything else red is this slice's to fix.

- [ ] **Step 2: Record**

Append to `_memory/2026-09-08-arv2-r2-account-agent.md`:

```
## R2 follow-ups DONE (2026-09-09, plan docs/superpowers/plans/2026-09-09-arv2-r2-followups.md)
- Catalog menu renders `[shape: …]` per schema'd field; `write_claims` receipts carry `expected_shape` + a
  `corrects_claim_id` hint on a schema miss; `agent_claims` drops null optional keys (`dropped_null_keys`).
- Established block: compact JSON, 240 chars/line; `research_deep` clips it to 6k chars with an omission note.
- Deep-call EVIDENCE_RULES: one assertion per sentence, quote first; a sentence per NOT FOUND item.
- `read_media_feeds(alternate_urls=[…])` falls through on load failures; `feed_not_found` names every URL.
- AI Ark HQ shape emits `region` (state) and `country_code` when the record has one.
- Not measured live (founder ruling): folds into R3's acceptance run.
```

- [ ] **Step 3: Commit**

```bash
git add _memory/2026-09-08-arv2-r2-account-agent.md docs/superpowers/plans/2026-09-08-arv2-r2-close.md
git commit -m "docs(arv2 r2 follow-ups): memory and plan cross-reference"
```

---

## Self-review

- **Spec coverage:** item 1 (shape at write time + null-dropping) → Task 1; item 2 (cap the established block) → Task 2; item 3 (quote-first prompt) → Task 3; item 4 (media alternates) → Task 4; item 5 (HQ region/country_code) → Task 5, with the honest note that exact grading against the key's codes is a grader question. "No re-run" → Global Constraints.
- **Placeholders:** the two `clients.exa_client.deep_calls[-1]["query"]` / `["system_prompt"]` accesses are flagged "adjust to the fake's real attribute" — the implementer must read `test_research_deep_returns_the_report_and_the_lock` and use whatever the fake records; that is a read, not a design decision. Same for the `MediaFetchError.__str__` text.
- **Type consistency:** `_receipt_json(receipt, draft, catalog)` is the only signature change and Task 1 names every caller; `_podcast_hop`/`_youtube_hop` take the URL as the third positional argument in Task 4 and nothing else calls them (`grep -n "_podcast_hop\|_youtube_hop"` to confirm).
