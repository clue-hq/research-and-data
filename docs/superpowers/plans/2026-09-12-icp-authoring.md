# ICP Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Head of ABM can author an ICP document itself — brand-level or project-local — as a `proposed` version the human confirms through the existing gate, and can request the persona synthesis turn for the confirmed ICP; project-local documents live in the same table with a `project_id` and are materialized under `inputs/project/`.

**Architecture:** One migration adds project scope and lineage to `brand_knowledge_document` and a `kind` to `onboarding_run`. A pure write function in `clue_api.arv2` authors the document (front matter owned by the platform, deterministic id, scope-aware lineage); a root-level tool binds the turn and calls it. The persona request creates a `personas` onboarding run that the existing fleet handler drives as exactly one persona step. Skill v23 / profile v46 / recipe v24 grant the two tools, following the R4 two-commit recipe (register ungranted, then grant).

**Tech Stack:** Python 3.12, SQLAlchemy async, Alembic, pydantic v2, the `clue_toolbelt` `Tool` envelope, the agent catalog (immutable versioned YAML/markdown), pytest on the lane DB.

**Spec:** `docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.2 (rulings R4, R5, R7). Depends on plan 1 (`agent_turn_project_files`, `project_context_files.py`).

## Global Constraints

- `platform/api/clue_api/arv2/` may import only `clue_api.arv2`, `clue_core`, `clue_config`, `clue_obs`, `clue_storage`, `clue_db`, `clue_gateway`, `clue_locks`, `clue_spine`, `clue_toolbelt`, `clue_fleet`, `clue_agents`, `clue_execution`, `clue_auth`, `clue_projections`, `clue_research.claimstore`, `clue_research.identity`, `clue_research.membership`, `clue_research.durable.project_run`, `clue_api.composition`, `clue_api.arv2_wiring` (`tests/arv2/test_import_guard.py`). Turn binding (`clue_api.turn_action`, `clue_api.turn_binding`) therefore lives in root-level tool modules.
- Profiles, skills, prompts and recipes are immutable: never edit `head-of-abm/v45`, `stage0-interview/v22`, `recipe0-stage0-v23.json`; copy to `v46` / `v23` / `v24`.
- `C6_AGENT_TOOL_AUTHORITY` must list every registered tool or the registry refuses to boot; a skill that names a tool forces a new skill version and a new profile version (pin equality is full `ToolPin` equality).
- Every address in `RECIPE_0_TOOL_ADDRESSES` needs typed output, certified replay, non-empty `pin_requirements`.
- `confirmed` rows are never retired by a new version (ruling 2026-09-10). The human's approval stamp never carries onto a new version.
- ICP `icp_key`: `^[a-z0-9]+(-[a-z0-9]+)*$`, ≤ 60 chars; unique per brand across scopes.
- Alembic: hash id, `down_revision` = plan 1's revision, reversible, one head.
- Tests: offline suites without `.env`; DB suites on the lane DB with `--ignore-glob='*_live.py' -p no:cacheprovider`; never `*_live.py`; never `make check`.
- No `git push`, no PRs, no AI attribution.

---

## File structure

| File | Responsibility |
|---|---|
| `alembic/versions/<hash>_arv2_project_scoped_documents.py` | `brand_knowledge_document.project_id`, `.derived_from_document_id`, the scope-aware unique index, folder/kind CHECK widening; `onboarding_run.kind`, `.project_id`, `.persona_icp_document_id`. |
| `platform/api/clue_api/brand_knowledge_context.py` | `KnowledgeDocumentRef.project_id`; brand readers filter `project_id IS NULL`; `current_project_knowledge_refs`; `workspace_paths` maps project-scoped refs under `inputs/project/`; `knowledge_seed_files` skips them. |
| `platform/api/clue_api/arv2/icp_confirmation.py` | `IcpDocumentSubject.project_id/derived_from_document_id`; `_servable_icp_rows` + `current_icp_document(project_id=)`; `confirm_icp_document` carries scope and lineage; `_CURRENT_PIN` selects `doc.project_id`. |
| `platform/api/clue_api/arv2/icp_authoring.py` | `IcpAuthoringRequest`, `AuthoredIcp`, `IcpAuthoringRefused`, `author_icp_document(conn, storage, request)`. |
| `platform/api/clue_api/icp_authoring_tools.py` | `AuthorIcpDocumentTool` (`author_icp_document@1`), `build_icp_authoring_tools`. |
| `platform/api/clue_api/arv2/onboarding_store.py` | `create_persona_run`; brand-level reads filter `project_id IS NULL`; `read_current_run` considers `kind = 'full'`. |
| `platform/api/clue_api/arv2/onboarding_driver.py` | `IcpRef.project_id`; `_Scope.kind/persona_icp`; `_run` branches to `_personas_only`. |
| `platform/api/clue_api/onboarding_routes.py` | `DbOnboardingEnqueuer.enqueue_personas`; the in-progress check considers `kind = 'full'`. |
| `platform/api/clue_api/onboarding_synthesis_wiring.py` | `RegisteredIcp.project_id`; `_current_input_documents` unions the ICP's project documents; `_register_documents` scope-aware lineage and `project_id` on insert. |
| `platform/api/clue_api/persona_request_tools.py` | `RequestPersonaSynthesisTool` (`request_persona_synthesis@1`), `build_persona_request_tools`. |
| `platform/api/clue_api/frontend_read/brand_knowledge.py` | Brand page reads and PUT filter `project_id IS NULL`. |
| `platform/api/clue_api/product_set_selection_gate_tools.py` | ICP pre-check sees project-local ICPs. |
| `platform/api/clue_api/chat/router.py` | Approve branch passes `project_id`. |
| `platform/api/clue_api/project_status.py`, `project_context_files.py`, `agent_turn_fleet_wiring.py` | Project documents join the project files pin and `status.md`. |
| `platform/agents/catalog/skills/stage0-interview/v23/SKILL.md`, `profiles/head-of-abm/v46/profile.yaml`, `platform/execution/recipes/recipe0-stage0-v24.json` | The grant. |
| Registration/tests | `toolbelt_wiring.py`, `agent_registry_wiring.py`, `recipe_contracts.py`, `recipe_wiring.py`, `stage0_recipe.py`, `conversation_turns.py`, `chat/composer_context.py`, `fleet_main.py`, `projections_main.py`, and the test files the R4 recipe lists. |
| `apps/frontend/src/features/projects/model/chat-tool-presentation.ts` | Labels for the two tools. |

---

### Task 1: Migration — project scope, lineage, and the persona run kind

**Files:**
- Create: `alembic/versions/<hash>_arv2_project_scoped_documents.py` (`down_revision` = plan 1's `agent_turn_project_files` revision)
- Test: `tests/db/test_arv2_project_scoped_documents_migration.py`

**Interfaces:**
- Produces on `brand_knowledge_document`: `project_id text NULL` (FK `(project_id, workspace_id) → project (project_id, workspace_id)`), `derived_from_document_id uuid NULL` (FK → `brand_knowledge_document (document_id)`); the constraint `brand_knowledge_document_path_version` dropped and replaced by `CREATE UNIQUE INDEX brand_knowledge_document_scope_path_version ON brand_knowledge_document (workspace_id, brand_id, COALESCE(project_id, ''), path, version)`; folder CHECK `IN ('company','product','audience','proof','design','project')`; kind CHECK adds `'project-plan'`; index `brand_knowledge_document_project ON (workspace_id, project_id, path, version DESC) WHERE project_id IS NOT NULL`.
- Produces on `onboarding_run`: `kind text NOT NULL DEFAULT 'full' CHECK (kind IN ('full','personas'))`, `project_id text NULL` (FK as above), `persona_icp_document_id uuid NULL` (FK → `brand_knowledge_document`), CHECK `onboarding_run_persona_shape ((kind = 'personas') = (persona_icp_document_id IS NOT NULL))`.

- [ ] **Step 1: Write the failing migration test** — copy the shape of `tests/db/test_arv2_project_icp_pin_migration.py`: upgrade; assert the two new columns on each table (`information_schema.columns`), the unique index by name in `pg_indexes`, that the old constraint name is gone from `pg_constraint`; insert two rows with the same `(workspace_id, brand_id, path, version)` and different `project_id` (NULL and `'prj'`) and assert no error; a third with the same scope raises `DBAPIError`; `INSERT INTO onboarding_run (... kind='personas', persona_icp_document_id=NULL)` raises `DBAPIError`; downgrade lands on the previous revision with the old constraint restored; upgrade again.

- [ ] **Step 2: Run it (fails)** — `set -a; source .env; set +a; uv run pytest tests/db/test_arv2_project_scoped_documents_migration.py -q -p no:cacheprovider`.

- [ ] **Step 3: Write the migration**

```python
def upgrade() -> None:
    op.execute("ALTER TABLE brand_knowledge_document ADD COLUMN project_id text")
    op.execute("ALTER TABLE brand_knowledge_document ADD COLUMN derived_from_document_id uuid")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_project_fk "
        "FOREIGN KEY (project_id, workspace_id) REFERENCES project (project_id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_derived_fk "
        "FOREIGN KEY (derived_from_document_id) REFERENCES brand_knowledge_document (document_id)"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_path_version"
    )
    op.execute(
        "CREATE UNIQUE INDEX brand_knowledge_document_scope_path_version ON brand_knowledge_document "
        "(workspace_id, brand_id, COALESCE(project_id, ''), path, version)"
    )
    op.execute(
        "CREATE INDEX brand_knowledge_document_project ON brand_knowledge_document "
        "(workspace_id, project_id, path, version DESC) WHERE project_id IS NOT NULL"
    )
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_folder")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_folder CHECK "
        "(folder IN ('company', 'product', 'audience', 'proof', 'design', 'project'))"
    )
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_kind")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_kind CHECK "
        "(kind IN ('company-overview', 'product-catalog', 'product-research', 'customer-reviews', "
        "'icp-definition', 'audience-persona', 'design-brief', 'project-plan'))"
    )
    op.execute(
        "COMMENT ON COLUMN brand_knowledge_document.project_id IS 'NULL = a brand-level document; "
        "set = a document scoped to one project (a project-local ICP variant, its personas, the "
        "project plan). Uniqueness of (path, version) is per scope.'"
    )
    op.execute("ALTER TABLE onboarding_run ADD COLUMN kind text NOT NULL DEFAULT 'full'")
    op.execute("ALTER TABLE onboarding_run ADD COLUMN project_id text")
    op.execute("ALTER TABLE onboarding_run ADD COLUMN persona_icp_document_id uuid")
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_kind CHECK (kind IN ('full', 'personas'))"
    )
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_project_fk "
        "FOREIGN KEY (project_id, workspace_id) REFERENCES project (project_id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_persona_icp_fk "
        "FOREIGN KEY (persona_icp_document_id) REFERENCES brand_knowledge_document (document_id)"
    )
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_persona_shape CHECK "
        "((kind = 'personas') = (persona_icp_document_id IS NOT NULL))"
    )
    op.execute(
        "CREATE INDEX onboarding_run_persona_open ON onboarding_run "
        "(persona_icp_document_id) WHERE kind = 'personas' AND status IN ('queued', 'running')"
    )


def downgrade() -> None:
    # Reverse order. The old UNIQUE constraint is restored verbatim; project-scoped rows (if any)
    # would violate it, so the downgrade refuses loudly when they exist.
    op.execute("DROP INDEX onboarding_run_persona_open")
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_persona_shape")
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_persona_icp_fk")
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_project_fk")
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_kind")
    op.execute("ALTER TABLE onboarding_run DROP COLUMN persona_icp_document_id")
    op.execute("ALTER TABLE onboarding_run DROP COLUMN project_id")
    op.execute("ALTER TABLE onboarding_run DROP COLUMN kind")
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_kind")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_kind CHECK "
        "(kind IN ('company-overview', 'product-catalog', 'product-research', 'customer-reviews', "
        "'icp-definition', 'audience-persona', 'design-brief'))"
    )
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_folder")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_folder CHECK "
        "(folder IN ('company', 'product', 'audience', 'proof', 'design'))"
    )
    op.execute("DROP INDEX brand_knowledge_document_project")
    op.execute("DROP INDEX brand_knowledge_document_scope_path_version")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_path_version "
        "UNIQUE (workspace_id, brand_id, path, version)"
    )
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_derived_fk")
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_project_fk")
    op.execute("ALTER TABLE brand_knowledge_document DROP COLUMN derived_from_document_id")
    op.execute("ALTER TABLE brand_knowledge_document DROP COLUMN project_id")
```

The PUT route maps `IntegrityError` by the constraint name `brand_knowledge_document_path_version` (`frontend_read/brand_knowledge.py:589-593`) — Task 2 renames that check to the new index name.

- [ ] **Step 4: Run the test; `uv run alembic heads` → one head.**

- [ ] **Step 5: Commit** — `git commit -m "feat(arv2): project-scoped knowledge documents and the personas onboarding run kind"`.

---

### Task 2: Scope every brand-level reader; project-aware ICP confirmation

**Files:**
- Modify: `platform/api/clue_api/brand_knowledge_context.py` (`KnowledgeDocumentRef`, `_DOCUMENT_COLUMNS`, `current_knowledge_documents`, `workspace_paths`, `knowledge_seed_files`, `_index_entry`), `platform/api/clue_api/arv2/icp_confirmation.py`, `platform/api/clue_api/arv2/onboarding_store.py:173,223,236,446,456`, `platform/api/clue_api/frontend_read/brand_knowledge.py:144-170,377-380,491,589-593`, `platform/api/clue_api/onboarding_synthesis_wiring.py:1272-1330,1370`, `platform/api/clue_api/product_set_selection_gate_tools.py:405-435`, `platform/api/clue_api/chat/router.py:2595-2600`, `platform/api/clue_api/icp_artifact_gate_tools.py:224-231`
- Test: `tests/api/test_brand_knowledge_context_db.py`, `tests/api/test_icp_artifact_gate_db.py`, `tests/api/test_chat_gate_answers_o6_db.py` (extend)

**Interfaces:**
- `KnowledgeDocumentRef` gains `project_id: str | None = None`; `_DOCUMENT_COLUMNS` adds `project_id`.
- `current_knowledge_documents(...)` adds `AND project_id IS NULL`.
- New `async def current_project_knowledge_refs(conn, *, workspace_id, project_id) -> tuple[KnowledgeDocumentRef, ...]` — `SELECT DISTINCT ON (path) … WHERE workspace_id = :ws AND project_id = :project AND status = ANY(:statuses) AND artifact_key IS NOT NULL ORDER BY path, version DESC`.
- `workspace_paths`: a ref with `project_id` maps to `PROJECT_INPUT_PREFIX + path` (import `PROJECT_INPUT_PREFIX` from `project_context_files`; `brand_knowledge_context` must not create an import cycle — put the constant in `brand_knowledge_context` and re-export it from `project_context_files`).
- `knowledge_seed_files`: skips refs with `project_id` (the project files pin seeds them).
- `IcpDocumentSubject` gains `project_id: str | None`, `derived_from_document_id: UUID | None`; `_servable_icp_rows(conn, *, workspace_id, brand_id, project_id: str | None)` selects both columns, filters `(project_id IS NULL OR project_id = :project_id)`, orders `ORDER BY path, (project_id IS NULL), version DESC` so a project-local row wins its path; `current_icp_document(..., project_id: str | None = None)`; `confirm_icp_document` INSERT carries `project_id` and `derived_from_document_id` from `proposed`; `_CURRENT_PIN` selects `doc.project_id` and `ProjectIcpPin` gains `project_id: str | None`.
- `_register_documents`: lineage and supersede SQL add `AND project_id IS NOT DISTINCT FROM :project_id`; INSERT adds `project_id`; `RegisteredIcp` gains `project_id: str | None = None` (Task 4 threads it).
- `brand_knowledge.py`: tree/detail reads add `AND d.project_id IS NULL`; the PUT's `FOR UPDATE` select and `MAX(version)` add `AND project_id IS NULL`; the `IntegrityError` name check becomes `"brand_knowledge_document_scope_path_version"`.
- `onboarding_store.py`: the five reads add `AND project_id IS NULL`.
- `product_set_selection_gate_tools._resolve`: `documents = (*await current_knowledge_documents(...), *await current_project_knowledge_refs(conn, workspace_id=…, project_id=turn.project_id))` before the ICP pre-check.
- `chat/router.py` approve branch and `icp_artifact_gate_tools._resolve`: pass `project_id=project_id` / `project_id=turn.project_id` to `current_icp_document`.

- [ ] **Step 1: Write the failing tests**

In `tests/api/test_brand_knowledge_context_db.py` add:

```python
def test_project_scoped_documents_are_invisible_to_brand_readers_and_seed_under_inputs_project(require_profiling_db) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, project_id, brand_id = ...  # existing seeding helpers
            brand_doc = await _insert_document(conn, ws, brand_id, path="audience/icp-gi.md", kind="icp-definition", version=1, status="proposed")
            project_doc = await _insert_document(conn, ws, brand_id, path="audience/icp-gi-dac.md", kind="icp-definition", version=1, status="proposed", project_id=project_id)
            refs = await current_knowledge_documents(conn, workspace_id=ws, brand_id=brand_id)
            assert [r.document_id for r in refs] == [brand_doc]
            project_refs = await current_project_knowledge_refs(conn, workspace_id=ws, project_id=project_id)
            assert [(r.document_id, r.project_id) for r in project_refs] == [(project_doc, project_id)]
            pinned = (PinnedDocument(ref=refs[0], body=b"", front_matter={}, body_text=""), PinnedDocument(ref=project_refs[0], body=b"", front_matter={}, body_text=""))
            paths = workspace_paths(pinned)
            assert paths[brand_doc] == "inputs/brand/knowledge/audience/icp-gi.md"
            assert paths[project_doc] == "inputs/project/audience/icp-gi-dac.md"
            assert [s.path for s in knowledge_seed_files(pinned)] == ["inputs/brand/knowledge/audience/icp-gi.md"]
    run_async(scenario())
```

In `tests/api/test_icp_artifact_gate_db.py` add a test: a project-local ICP (`project_id` set) resolves through `current_icp_document(..., project_id=project_id)`; the same key with another project's id returns `None`; the gate tool opens on it. In `tests/api/test_chat_gate_answers_o6_db.py` add: approving a project-local ICP mints a `confirmed` version with the same `project_id` and `derived_from_document_id`, and pins it.

- [ ] **Step 2: Run them (fail).**

- [ ] **Step 3: Make the changes listed under Interfaces.** Keep every SQL string's parameter names; add the filter as the last predicate. For `_servable_icp_rows`:

```python
_SERVABLE_ICP_ROWS = text(
    "SELECT DISTINCT ON (path) document_id, brand_id, project_id, derived_from_document_id, "
    " path, version, status, artifact_key, artifact_sha256 "
    "FROM brand_knowledge_document "
    "WHERE workspace_id = :workspace_id AND brand_id = :brand_id AND kind = :kind "
    " AND status = ANY(:statuses) AND artifact_key IS NOT NULL "
    " AND (project_id IS NULL OR project_id = :project_id) "
    "ORDER BY path, (project_id IS NULL), version DESC"
)
```

(`:project_id` is passed as `None` when unscoped; `NULL = NULL` is not true, so an unscoped read sees brand rows only.)

`confirm_icp_document`'s INSERT: add `project_id, derived_from_document_id` columns with `:project_id, :derived_from` bound from `proposed`. Its lineage `MAX(version)` read adds `AND project_id IS NOT DISTINCT FROM :project_id`.

- [ ] **Step 4: Run** the three test files plus `tests/api/test_product_set_selection_gate_tool_db.py tests/api/test_onboarding_synthesis_wiring_db.py tests/api/test_o6_conversation_composition_db.py tests/arv2 tests/api/test_frontend_read_brand_knowledge*.py` (whatever exists under `tests/api` for `brand_knowledge`) on the lane DB; `uv run ruff check` and `uv run mypy` on the touched modules; `uv run pytest tests/arv2/test_import_guard.py -q`.

- [ ] **Step 5: Commit** — `git commit -m "feat(arv2): brand readers see brand-level rows only; ICP confirmation and the pin carry project scope and lineage"`.

---

### Task 3: `author_icp_document` — the write function and the tool (registered ungranted)

**Files:**
- Create: `platform/api/clue_api/arv2/icp_authoring.py`, `platform/api/clue_api/icp_authoring_tools.py`
- Modify: `platform/api/clue_api/arv2/__init__.py` (re-exports), `platform/api/clue_api/toolbelt_wiring.py` (`icp_authoring: IcpAuthoringService | None = None` kwarg; register), `platform/api/clue_api/agent_registry_wiring.py` (`"author_icp_document": ()`), `platform/api/clue_api/fleet_main.py` and `projections_main.py` (compose `DbIcpAuthoringService(storage)` when `storage is not None`)
- Test: `tests/arv2/test_icp_authoring_db.py`, `tests/api/test_icp_authoring_tool.py` (offline), plus the count bumps in `tests/api/test_toolbelt_wiring.py`, `tests/agents/test_tool_authority_audit.py`, `tests/api/test_agent_registry_wiring.py`

**Interfaces:**

```python
# clue_api.arv2.icp_authoring
ICP_KEY_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

@dataclass(frozen=True, slots=True)
class IcpAuthoringRequest:
    workspace_id: str
    brand_id: str
    project_id: str
    turn_id: UUID
    user_id: str
    icp_key: str
    document_text: str
    scope: Literal["brand", "project"]
    derived_from_icp_key: str | None

@dataclass(frozen=True, slots=True)
class AuthoredIcp:
    document_id: UUID
    icp_key: str
    version: int
    path: str
    workspace_path: str      # inputs/brand/knowledge/… or inputs/project/…
    status: str              # "proposed"
    replayed: bool

class IcpAuthoringRefused(Exception):
    def __init__(self, code: str, message: str) -> None

def authored_document_id(*, turn_id: UUID, scope: str, icp_key: str) -> UUID   # uuid5(NAMESPACE_URL, f"arv2-icp-authoring:{turn_id}:{scope}:{icp_key}")

async def author_icp_document(conn, storage, request: IcpAuthoringRequest, *, now=_utcnow) -> AuthoredIcp
```

Refusal codes: `icp_key_invalid`, `icp_front_matter_invalid` (with the reason in the message), `icp_key_taken_by_brand`, `icp_key_taken_by_project`, `derived_from_not_found`, `icp_document_version_race`.

Tool:

```python
class AuthorIcpDocumentInput(ToolInput):
    icp_key: str = Field(min_length=1, max_length=60, pattern=ICP_KEY_PATTERN)
    document: str = Field(min_length=1, max_length=200_000)
    scope: Literal["brand", "project"]
    derived_from_icp_key: str | None = None
    source_turn_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})

class AuthorIcpDocumentOutput(ToolOutput):
    document_id: str; icp_key: str; version: int; path: str; workspace_path: str; status: str; replayed: bool

class AuthorIcpDocumentTool(Tool):
    name = "author_icp_document"; version = "1"
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(policy=ReplayPolicy.DOMAIN_IDEMPOTENT, durable_identity="presenting turn + scope + icp_key", external_boundary=ExternalReplayBoundary.NONE)
    parameter_policy = JournalParameterPolicy(safe_display_fields=("icp_key", "scope", "derived_from_icp_key"))
    pin_requirements = ("project",)
```

`model_description` (verbatim): "Store an ICP document you drafted from the brand's knowledge files as a proposed version — brand-level (a new profile for the whole brand) or project-local (a variant for this project only, with its own key and derived_from naming the brand profile it adapts). The document must carry the icp-definition front matter: kind, icp_key, product_ids, hard_gates, exclusions, persona_map, qualifier_fields, then the body. The platform owns status, scope and lineage. Nothing is confirmed by this call: open the ICP confirmation gate afterwards."

The tool's `_resolve` copies `icp_artifact_gate_tools._resolve` lines 207–228 (turn ref → turn identity → project in workspace) and builds the request with `turn.project_id`, `project.brand_id`, `turn.submitted_by_user_id`. `preconditions` returns `icp_authoring_not_composed` when the service is `None`; `invoke` maps `IcpAuthoringRefused` to `PreconditionFailed([PreconditionFailure(code, msg)])`.

- [ ] **Step 1: Write the failing DB test** (`tests/arv2/test_icp_authoring_db.py`, using the seeding helpers of `tests/arv2/test_discovery_launch_db.py` and the ICP fixture in `tests/arv2/icp_fixture.py`):

```python
_DOC = """---
kind: icp-definition
icp_key: gi-dac
product_ids: [prd_aura]
hard_gates:
  - {key: specialty, rule: GI-focused ambulatory surgery centre, test: website lists GI procedures}
exclusions: [academic medical centres]
persona_map:
  economic_buyer: {titles: [Administrator]}
qualifier_fields:
  - {field_key: account.gi_case_volume, description: annual GI case volume, display: rail}
---

# GI-focused ASCs

Body.
"""

def test_a_project_local_variant_is_stored_proposed_with_scope_and_lineage(require_profiling_db) -> None:
    async def scenario() -> None:
        storage = _MemoryStorage()
        async with rollback_conn() as conn:
            ws, project_id, brand_id = await _seed(conn)
            brand_icp = await insert_icp_document(conn, storage, ws, brand_id, icp_key="gi", ...)   # icp_fixture
            turn_id = await _seed_submission(conn, ws, project_id)
            request = IcpAuthoringRequest(ws, brand_id, project_id, turn_id, "usr_1", "gi-dac", _DOC, "project", "gi")
            first = await author_icp_document(conn, storage, request)
            assert (first.version, first.status, first.replayed) == (1, "proposed", False)
            assert first.workspace_path == "inputs/project/audience/icp-gi-dac.md"
            row = (await conn.execute(text("SELECT project_id, derived_from_document_id, status, folder, kind FROM brand_knowledge_document WHERE document_id = :d"), {"d": first.document_id})).mappings().one()
            assert row == {"project_id": project_id, "derived_from_document_id": brand_icp, "status": "proposed", "folder": "audience", "kind": "icp-definition"}
            front, body = parse_front_matter(storage.get_sync(...).decode(), preserve_body=True)
            assert front["status"] == "proposed" and front["project_id"] == project_id and front["derived_from"] == str(brand_icp)
            assert front["authored_by"] == {"turn_id": str(turn_id), "user_id": "usr_1"}
            again = await author_icp_document(conn, storage, request)
            assert again.replayed and again.document_id == first.document_id


def test_refusals_are_typed(require_profiling_db) -> None:
    # scope=project with an existing brand-level `gi` → icp_key_taken_by_brand
    # scope=brand with an existing project-local `gi-dac` → icp_key_taken_by_project
    # derived_from_icp_key unknown → derived_from_not_found
    # front matter missing hard_gates → icp_front_matter_invalid
    # a second turn authoring the same project key → version 2, supersedes version 1 (status superseded)
    ...
```

- [ ] **Step 2: Run (fails).**

- [ ] **Step 3: Write `icp_authoring.py`**

```python
async def author_icp_document(conn, storage, request, *, now=_utcnow) -> AuthoredIcp:
    if re.fullmatch(ICP_KEY_PATTERN, request.icp_key) is None or len(request.icp_key) > 60:
        raise IcpAuthoringRefused("icp_key_invalid", "icp_key must be lowercase kebab-case, at most 60 characters")
    try:
        front, body = parse_front_matter(request.document_text, preserve_body=True)
    except ValueError as exc:
        raise IcpAuthoringRefused("icp_front_matter_invalid", str(exc)) from exc
    _validate_front(front, icp_key=request.icp_key)      # kind, icp_key, product_ids (non-empty list of str), hard_gates (non-empty list)
    document_id = authored_document_id(turn_id=request.turn_id, scope=request.scope, icp_key=request.icp_key)
    existing = await _existing(conn, document_id)          # replay → AuthoredIcp(replayed=True)
    if existing is not None:
        return existing
    path = f"audience/icp-{request.icp_key}.md"
    scope_project = request.project_id if request.scope == "project" else None
    await _refuse_cross_scope(conn, request, path=path)    # the two *_taken_by_* refusals
    derived_from = await _derived_from(conn, request)      # None, a brand document id, or derived_from_not_found
    front = {k: v for k, v in front.items() if k not in ("confirmed_by", "confirmed_at", "confirmed_for_project_id", "product_selection_version", "user_edit")}
    front["status"] = "proposed"
    front["brand_id"] = request.brand_id
    if scope_project is not None:
        front["project_id"] = scope_project
    else:
        front.pop("project_id", None)
    if derived_from is not None:
        front["derived_from"] = str(derived_from)
    front["authored_by"] = {"turn_id": str(request.turn_id), "user_id": request.user_id}
    front["authored_at"] = now().isoformat()
    data = render_markdown(KnowledgeDocument(kind="icp-definition", folder="audience", path=path, front_matter=front, body=body, cost=None)).encode("utf-8")
    sha = content_address(data); key = artifact_key(request.workspace_id, sha)
    await record_artifact(conn, storage_key=key, workspace_id=request.workspace_id, content_sha256=sha, media_type="text/markdown", size_bytes=len(data), source_key="arv2-icp-authoring")
    await storage.put(key, data, media_type="text/markdown")
    lineage = ...  # next_version + supersedes over rows WHERE ws/brand/path AND project_id IS NOT DISTINCT FROM :scope_project (copy the SQL at onboarding_synthesis_wiring.py:1280-1300 with the extra predicate)
    try:
        await conn.execute(text("INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, project_id, folder, path, kind, version, status, artifact_key, artifact_sha256, supersedes_document_id, derived_from_document_id) VALUES (:id, :ws, :brand, :project, 'audience', :path, 'icp-definition', :version, 'proposed', :key, :sha, :supersedes, :derived) ON CONFLICT (document_id) DO NOTHING"), {...})
    except IntegrityError as exc:
        if "brand_knowledge_document_scope_path_version" in str(exc.orig):
            raise IcpAuthoringRefused("icp_document_version_race", "another writer published this path meanwhere; re-read and retry") from exc
        raise
    await conn.execute(text("UPDATE brand_knowledge_document SET status = 'superseded', updated_at = now() WHERE workspace_id = :ws AND brand_id = :brand AND path = :path AND project_id IS NOT DISTINCT FROM :project AND document_id <> :id AND status IN ('ready', 'proposed')"), {...})
    return AuthoredIcp(document_id, request.icp_key, version, path, workspace_path, "proposed", replayed=False)
```

`authored_at` is the one non-deterministic value; it is inside the artifact bytes, which is fine because replay short-circuits before rendering (the R4 discipline).

- [ ] **Step 4: Write the tool module, register ungranted, compose the service.** In `toolbelt_wiring.build_toolbelt` add the kwarg and `for tool in build_icp_authoring_tools(icp_authoring): registry.register(tool, make_default=True)`. `DbIcpAuthoringService(storage, conn_factory=transaction)` exposes `async def author(self, request) -> AuthoredIcp` (one transaction). Compose it in `fleet_main.py` (next to `DbArv2DiscoveryService`) and `projections_main.py` whenever `storage is not None` — no new env flag. Add `"author_icp_document": ()` to `C6_AGENT_TOOL_AUTHORITY`. Bump the counts the R4 recipe names (`tests/api/test_toolbelt_wiring.py` `_MATRIX` entry `("precondition", ("icp_authoring_not_composed",))`, `len(registry.names())`; `tests/agents/test_tool_authority_audit.py`; `tests/api/test_agent_registry_wiring.py` inventory comment).

- [ ] **Step 5: Offline tool tests** (`tests/api/test_icp_authoring_tool.py`, shape of `tests/api/test_arv2_launch_tools.py`): uncomposed refusal; malformed `source_turn_ref` → `gate_turn_ref_malformed`-style code (`authoring_turn_ref_malformed`); a scripted service receiving the derived request (workspace from `ctx`, project/brand/user from the turn); a refusal mapped to `PreconditionFailed`; descriptor classes (`effect_class == WRITE`, `recipe_safe`, `pin_requirements == ("project",)`, `source_turn_ref` absent from the model-visible schema).

- [ ] **Step 6: Run** `tests/arv2 tests/api/test_icp_authoring_tool.py tests/api/test_toolbelt_wiring.py tests/agents tests/api/test_agent_registry_wiring.py --ignore-glob='*_live.py' -p no:cacheprovider -q`; ruff; mypy; `uv run lint-imports`.

- [ ] **Step 7: Commit** — `git commit -m "feat(arv2): author_icp_document — a proposed ICP version authored by the Head of ABM, brand-level or project-local, registered ungranted"`.

---

### Task 4: The persona synthesis request

**Files:**
- Modify: `platform/api/clue_api/arv2/onboarding_store.py` (`create_persona_run`, `read_current_run` filter), `platform/api/clue_api/arv2/onboarding_driver.py` (`IcpRef.project_id`, `_Scope.kind` + `persona_icp`, `_run` branch, `_scope` payload parsing), `platform/api/clue_api/onboarding_routes.py` (`DbOnboardingEnqueuer.enqueue_personas`; the 409 check adds `AND kind = 'full'`), `platform/api/clue_api/onboarding_synthesis_wiring.py` (`RegisteredIcp.project_id`, `_current_input_documents(..., project_id)`, `_register_documents` uses `icp.project_id` for persona output), `platform/api/clue_api/fleet_main.py` (`_SynthesisSeam` copies `project_id` both ways)
- Create: `platform/api/clue_api/persona_request_tools.py`
- Modify: `toolbelt_wiring.py`, `agent_registry_wiring.py` (`"request_persona_synthesis": ()`), `fleet_main.py`, `projections_main.py`
- Test: `tests/arv2/test_persona_run_db.py`, `tests/api/test_persona_request_tool.py`, `tests/api/test_onboarding_synthesis_wiring_db.py` (extend), `tests/api/test_onboarding_routes*.py` (the 409 check)

**Interfaces:**

```python
# onboarding_store
async def create_persona_run(conn, *, run_id: UUID, workspace_id: str, brand_id: str, project_id: str, persona_icp_document_id: UUID, company_domain: str, requested_by_user_id: str) -> None
#   INSERT … kind='personas', project_id, persona_icp_document_id … ON CONFLICT DO NOTHING
async def open_persona_run(conn, *, persona_icp_document_id: UUID) -> UUID | None
#   SELECT run_id … WHERE kind='personas' AND persona_icp_document_id = :d AND status IN ('queued','running')
# read_current_run: WHERE workspace_id = :ws AND kind = 'full'

# onboarding_driver
@dataclass(frozen=True) class IcpRef: document_id; icp_key; version; path; project_id: str | None = None
@dataclass(frozen=True) class _Scope: run_id; workspace_id; brand_id; company_domain; company_name; kind: Literal["full","personas"] = "full"; persona_icp: IcpRef | None = None
# _run: if scope.kind == "personas": return await self._personas_only(scope)
async def _personas_only(self, scope) -> str:
    async with self._connection() as conn: await self._store.mark_run_running(conn, run_id=scope.run_id)
    assert scope.persona_icp is not None
    await self._persona_step(scope, scope.persona_icp)
    async with self._connection() as conn: return str(await self._store.finish_run(conn, run_id=scope.run_id))

# onboarding_routes.DbOnboardingEnqueuer
async def enqueue_personas(self, *, run_id, workspace_id, brand_id, project_id, company_domain, company_name, icp: IcpRef) -> bool
#   same kind/priority/dedup as enqueue(); payload adds "kind": "personas", "icp": {"document_id","icp_key","version","path","project_id"}

# persona_request_tools
class RequestPersonaSynthesisInput(ToolInput): icp_key: str; source_turn_ref (trusted)
class RequestPersonaSynthesisOutput(ToolOutput): run_id: str; icp_key: str; replayed: bool
class RequestPersonaSynthesisTool(Tool):
    name = "request_persona_synthesis"; version = "1"; effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(policy=ReplayPolicy.DOMAIN_IDEMPOTENT, durable_identity="project + pinned ICP document; one open personas run per document", external_boundary=ExternalReplayBoundary.NONE)
    parameter_policy = JournalParameterPolicy(safe_display_fields=("icp_key",)); pin_requirements = ("project",)
```

`model_description`: "Ask the platform to write (or rewrite) the persona document for this project's confirmed ICP. Runs the audience-persona synthesis turn in the background; the document lands under the same scope as the ICP on a later turn. Call only when the human wants personas for a newly confirmed profile, or asks for a redraft. Refused when the ICP named is not this project's pinned ICP, or when a persona run for it is already open."

Refusal codes: `persona_synthesis_not_composed`, `icp_not_pinned_for_project` (the key is not the project's current pin), `persona_run_already_open`, `brand_not_onboarded` (no completed `full` run to take `company_domain` from). `run_id = uuid5(NAMESPACE_URL, f"arv2-persona-run:{workspace_id}:{pin.document_id}:{turn_id}")` so a replayed tool call within one turn finds its own run (`replayed=True`).

The service (`DbPersonaRequestService(queue, conn_factory)`): resolve the pin (`current_project_icp_pin`), compare `pin.icp_key == icp_key`, check `open_persona_run`, read the newest completed full run's `company_domain` for the brand, `create_persona_run`, commit, then `enqueue_personas`. Same failed-offer containment as `start_onboarding` (`fail_run` + typed refusal `enqueue_failed`).

- [ ] **Step 1: Failing tests** — `tests/arv2/test_persona_run_db.py`: `create_persona_run` + `open_persona_run`; `read_current_run` ignores a `personas` run; the driver's `_scope` parses the personas payload; `_personas_only` runs exactly one persona step (scripted `SynthesisLauncher` recording the `IcpRef` with `project_id`) and finishes the run. `tests/api/test_onboarding_synthesis_wiring_db.py`: a persona task for a project-local ICP selects that ICP from the project's documents and registers the persona with the same `project_id`. `tests/api/test_persona_request_tool.py`: offline tool tests as in Task 3 Step 5. Route test: the 409 `onboarding_in_progress` ignores an open `personas` run.

- [ ] **Step 2: Run (fail). Step 3: implement. Step 4: run the files above plus `tests/fleet`, ruff, mypy, `lint-imports`, `tests/arv2/test_import_guard.py`.**

- [ ] **Step 5: Commit** — `git commit -m "feat(arv2): request_persona_synthesis — a personas-only onboarding run for the project's pinned ICP, registered ungranted"`.

---

### Task 5: Project documents join the project folder and `status.md`

**Files:**
- Modify: `platform/api/clue_api/project_status.py` (`load_project_status_facts` fills `documents` from `current_project_knowledge_refs`), `platform/api/clue_api/project_context_files.py` (`current_project_documents(conn, storage, *, workspace_id, project_id) -> list[CompiledProjectFile]`), `platform/api/clue_api/agent_turn_fleet_wiring.py` (`compile_project_files` appends `await current_project_documents(...)`)
- Test: `tests/api/test_project_context_files_db.py` (extend), `tests/api/test_o6_conversation_composition_db.py` (extend)

- [ ] **Step 1: Failing test** — with a project-local ICP row (as in Task 2's test) the production turn seeds `inputs/project/audience/icp-gi-dac.md` read-only, the project files index lists it with `kind == "icp-definition"`, `version == 1`, `status == "proposed"`, and `status.md`'s "Project documents" section names it.

- [ ] **Step 2–3: implement.** `current_project_documents` reads each ref's verified bytes (`read_verified_artifact`, digest compared to `artifact_sha256`, mismatch → `ProjectFilesPinConflict`) and returns `CompiledProjectFile(path=ref.path, kind=ref.kind, body=bytes, version=ref.version, status=ref.status, summary=summary_of(bytes))`. `ProjectDocumentFacts` rows come from the same refs (`updated_at` from the row).

- [ ] **Step 4: Run** the two test files; **Step 5: Commit** — `git commit -m "feat(project-context): project-scoped documents materialize under inputs/project/ and appear in status.md"`.

---

### Task 6: The grant — skill v23, profile v46, recipe v24

**Files:**
- Create: `platform/agents/catalog/skills/stage0-interview/v23/SKILL.md` (copy of v22), `platform/agents/catalog/profiles/head-of-abm/v46/profile.yaml` (copy of v45), `platform/execution/recipes/recipe0-stage0-v24.json` (copy of v23)
- Modify: `agent_registry_wiring.py` (`C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM] = "v46"`; both authority rows → `(AgentRole.HEAD_OF_ABM,)`; both names added to `STAGE0_CONVERSATION_TRIAL_SURFACE.withheld_tools`), `chat/composer_context.py` (`"head-of-abm@v46"`), `recipe_contracts.py` (two addresses), `recipe_wiring.py` (`"recipe0-stage0-v24.json"`), `conversation_turns.py` (`CONVERSATION_RECIPE_VERSION = 24`), `stage0_recipe.py` (both names in the `_presenting_turn_project_pin` branch, beside `open_icp_confirmation_gate`), and the tests the R4 recipe lists (`tests/agents/test_catalog.py`, `tests/agents/test_tool_authority_audit.py`, `tests/api/test_agent_registry_wiring.py` incl. the new manifest digest, `tests/api/test_c8_trial_surface.py`, `tests/api/test_client_knowledge_privacy_s4e.py`, `tests/api/test_comprehensive_research_contract.py`, `tests/api/test_recipe_contracts.py` with `test_mints_recipe_v24_without_rewriting_v23`)

**Skill v23 — the text changes (everything else stays v22 verbatim):**

Front matter: `version: v23`; `summary:` append "…, author an ICP document when the brand's proposals do not fit, and request its personas."; `tools:` add both pins (digests read off the live descriptor: `build_toolbelt(storage=None, gateway=None).descriptor("author_icp_document", "1")`).

§1, add after the first bullet:

```
- Also before your first reply on a thread, read `inputs/project/status.md` and `inputs/project/decisions.md`. `status.md` is compiled by the platform from the project's rows: the confirmed ICP, the product set, the plan, the accounts, discovery and research. `decisions.md` is what the human already told this project, in their words. Another thread of this project may have done the work; these two files are how you know. Re-read `status.md` before answering any question about where the project stands.
- A project's own documents live under `inputs/project/`: a project-local ICP at `inputs/project/audience/icp-<key>.md`, its personas at `inputs/project/audience/persona-<key>.md`, the plan at `inputs/project/plan.md`. They appear on the turn after they are written.
```

§3, replace the second and third outcomes with:

```
- **The user describes their own profile and it differs in a few points.** Ask whether the changes hold for the whole brand or only for this project. Then draft the profile (section 5b) with `scope: "brand"` — a new version of the brand profile under the same key — or `scope: "project"` — a variant with its own key and `derived_from_icp_key` naming the profile it adapts. Then confirm it through the gates.
- **The user says none of the proposals fit.** Draft a new profile from the files (section 5b), brand-level unless the user says it is for this project only. Then confirm it through the gates.
```

§5, replace the *Revised* bullet with:

```
- **Revised** carries the human's requested changes in the gate receipt. Apply them: draft the revised profile (section 5b) in the same scope as the reviewed one, then open the confirmation gate on the new version. Record the human's words in project context as well (section 6).
```

New §5b after §5:

```
## 5b. Author a profile

You may write an ICP document. You may not confirm one — the human does that through the gate.

Draft only from the files under `inputs/brand/knowledge/`: `company/overview.md`, `product/catalog.md`, the product files, `proof/customer-reviews.md`, and the existing `audience/icp-*.md`. Every hard gate must trace to something in those files or to what the human told you (section 6). If you cannot trace it, leave it out. Never invent a product id: take `product_ids` from `product/catalog.md`'s front matter.

Write the whole document — the front matter and the body — in the shape the existing ICP files use: `kind: icp-definition`, `icp_key`, `product_ids`, `hard_gates` (each `{key, rule, test}`), `exclusions`, `persona_map` (only the roles that exist at this account type), `qualifier_fields`; then the body in priority order: who fits and why, the list math, disqualifiers and red flags, the client's own phrasing quoted from the files, the qualification-floor verdict. Choose a lowercase kebab-case `icp_key` that is not already in use; a project variant needs its own key, never the brand profile's.

Call `author_icp_document` with `icp_key`, `document`, `scope` (`brand` or `project`) and, for a variant, `derived_from_icp_key`. The platform sets the status to proposed and records who wrote it. The receipt names the path the file will have on your next turn. In the same turn, open the ICP confirmation gate on that key (section 5) and end the turn `awaiting_input`. A refusal names what to fix: a key already taken, a missing gate, a product id the catalog does not carry.

Do not write a profile before the questions in section 2 are answered, and do not write one the user did not ask for.
```

New §5c after §5b:

```
## 5c. Personas for a confirmed profile

A profile the human confirmed through the gate needs its persona document before research and outreach can use it. On the turn after the confirmation, when the index card names the confirmed ICP as this project's pin, ask the human whether to write the personas now. If they say yes, call `request_persona_synthesis` with the `icp_key`. The platform runs the persona turn in the background; the document lands under the same scope as the profile on a later turn (`inputs/brand/knowledge/audience/persona-<key>.md` or `inputs/project/audience/persona-<key>.md`). Say that it is running, not that it is done. If the human wants a persona rewritten later, the same call redrafts it.
```

§10 replace with:

```
## 10. What you cannot do

You cannot confirm an ICP or a product set, edit a knowledge document the platform or the human wrote, research the web, declare a company ready, or start anything the human has not asked for on the current turn. You may author a proposed ICP document (section 5b) and request its personas (section 5c); confirmation stays the human's. There is no readiness check and no recon on this surface. The knowledge is in the files, and the files are what you read.
```

**Profile v46:** `version: v46`, header comment ("v46 (ARV2 context and authoring, 2026-09-12): v45 plus `author_icp_document@1` and `request_persona_synthesis@1`; skill pin moved v22→v23"), skill pin `stage0-interview@v23` with the new file's sha256, the two tool pins. Nothing else changes.

**Recipe v24:** v23 plus both addresses at the four sites; `"version": 24`.

- [ ] **Step 1: Mint the three files, flip the registry, run the registry test to read the new manifest digest, paste it.**
- [ ] **Step 2: Run** the R4 gate command (`tests/arv2 tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py tests/api/test_toolbelt_wiring.py tests/agents tests/api/test_c8_trial_surface.py tests/api/test_client_knowledge_privacy_s4e.py tests/api/test_comprehensive_research_contract.py --ignore-glob='*_live.py' -p no:cacheprovider -q`) twice, plus `tests/execution/test_recipes.py` on the lane DB, `uv run lint-imports`.
- [ ] **Step 3: Commit** — `git commit -m "feat(head-of-abm): v46 grants author_icp_document@1 and request_persona_synthesis@1 — skill v23 teaches drafting, scope and personas; recipe v24 admits them"`.

---

### Task 7: Frontend labels, docs, live proof, close-out

**Files:**
- Modify: `apps/frontend/src/features/projects/model/chat-tool-presentation.ts` (`TOOL_LABELS`: `author_icp_document: "Draft an ideal customer profile"`, `request_persona_synthesis: "Write the buyer personas"`), `apps/frontend/src/features/projects/model/chat-tool-presentation.test.ts` (two label assertions), `platform/api/clue_api/arv2/README.md` (a section "ICP authoring and project-scoped documents"), `docs/specs/ARV2-ONBOARDING-PLAN.md` §8 addendum, `_memory/2026-09-12-icp-authoring.md` + `_memory/README.md`.

- [ ] **Step 1: Labels + test**; run `cd apps/frontend && npm test -- --test-name-pattern="tool-presentation"` (or the file's own runner line) and `npm run lint`.
- [ ] **Step 2: Restart this lane's API twins and workers** (`./scripts/dev_stack_san_salvador.sh restart-api > /tmp/san-salvador_restart.log 2>&1; ./scripts/dev_stack_san_salvador.sh restart-workers >> /tmp/san-salvador_restart.log 2>&1`).
- [ ] **Step 3: Live walk** on a fresh project of the founder's brand: interview → say the proposals do not fit → the agent drafts (tool `author_icp_document` visible in the transcript) → gate card → approve → next turn the index card and `status.md` name the new ICP → agent offers personas → `request_persona_synthesis` → a `personas` onboarding run appears (`SELECT run_id, kind, status FROM onboarding_run ORDER BY requested_at DESC LIMIT 1`) → the persona document lands with the ICP's scope. Record the SQL results and the transcript summary in the memory note. Any refusal or mis-scoped row is a defect to fix before close-out.
- [ ] **Step 4: Commit** — `git commit -m "docs(arv2): ICP authoring close-out — labels, README, memory"`.

---

## Self-review

- Spec §4.2 coverage: schema (T1), reader scoping + gate/pin (T2), authoring tool with the listed refusals (T3), persona request + personas-only run + `read_current_run`/409 filters (T4), materialization of project documents (T5), skill/profile/recipe (T6), labels (T7). ✔
- Placeholder scan: every `...` in test sketches names the helper file it copies from; no "TBD". ✔
- Type consistency: `IcpAuthoringRequest` positional order `(workspace_id, brand_id, project_id, turn_id, user_id, icp_key, document_text, scope, derived_from_icp_key)` matches the test; `IcpRef.project_id` / `RegisteredIcp.project_id` both default `None`; `current_icp_document(project_id=)` keyword-only in T2 and used so in T3's gate; `authored_document_id` keyword-only. ✔
