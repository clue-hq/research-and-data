# Conversation naming — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chat started from Home or inside a project earns a 2–5-word generated title, and a Home-created project earns a generated name, from one cheap model call at the end of the first completed turn — replacing "Untitled project", "New chat" and the 80-character first-message prefix — without ever delaying the turn or overwriting a human rename.

**Architecture:** A `ConversationNamer` service (`platform/api/clue_api/conversation_naming.py`) makes one OpenRouter chat-completions call through the spend-ledger `ProviderCaller`, normalises the two names, and writes them with conditional `UPDATE … WHERE title IS NULL` / `WHERE name = 'Untitled project'` statements. The Head-of-ABM `ConversationTurnEngine` starts the namer as a task the moment the assistant reply is known, waits at most `NAMING_GRACE_S = 3.0` s before emitting the terminal turn event, and lets a slow call finish detached. The Home bootstrap route births the thread untitled. The frontend already invalidates the project catalog on terminal turn events; it gains a bounded catch-up poll while a placeholder is still visible.

**Tech Stack:** FastAPI + pydantic + SQLAlchemy text SQL, `clue_spend.ProviderCaller` over `HttpxTransport`, `asyncio` (backend); Next.js App Router, Zod, `node:test` via `tsx` (frontend).

**Spec:** `docs/superpowers/specs/archive/2026-09-18-conversation-naming-design.md`.

## Global Constraints

- Local commits only; never `git push`; never `git stash`; no AI attribution in commit messages.
- Never run `make check`, whole suites, or `*_live.py`. Backend: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest <files> -p no:cacheprovider --ignore-glob='*_live.py'` (the lane DB is `clue_trenton` on :55040; the trenton stack is down, so DB suites are safe). Frontend from `apps/frontend`: `npm test`, `npm run lint`, `npx tsc --noEmit -p .` (three pre-existing test-file errors are known); `npm run build` only with the lane dev server stopped.
- Every new setting appears in `.env.example` AND the lane `.env` in the same task that introduces it (parity rule 2026-08-31). Exactly three: `CLUE_CONVERSATION_NAMING_ENABLED=true`, `CLUE_CONVERSATION_NAMING_MODEL=openai/gpt-5.6-luna`, `CLUE_CONVERSATION_NAMING_TIMEOUT_S=60.0`.
- Constants (verbatim): `NAMING_GRACE_S = 3.0`, `NAMING_INPUT_CHARS = 2_000`, `NAMING_MAX_TOKENS = 60`, `NAMING_MAX_CODE_POINTS = 60`, `NAMING_MAX_WORDS = 8`, `NAMING_LABEL = "conversation_naming"`, `UNTITLED_PROJECT_NAME = "Untitled project"`, frontend `UNTITLED_THREAD_LABEL = "New chat"` (already exists), poll every 5 000 ms at most 12 times.
- The namer is a service step, not a tool: it never goes through `rename_thread` / `rename_project`, never appears in a profile or manifest, and never raises into the turn.
- No migration. No new SSE event type. No new UI copy.
- Do not dispatch subagents from inside a task; report back.

---

## File map

| file | change |
|---|---|
| `libs/clue-spine/clue_spine/spine.py`, `__init__.py` | `UNTITLED_PROJECT_NAME`, `set_project_name_if_untitled` |
| `platform/api/clue_api/thread_store.py` | `set_thread_title_if_unset` |
| `libs/clue-config/clue_config/settings.py`, `.env.example`, `.env` | three `conversation_naming_*` settings |
| `platform/api/clue_api/conversation_naming.py` (new) | normaliser, prompt, request/outcome types, `ConversationNamer` protocol, `OpenRouterConversationNamer`, `build_conversation_namer`, `TurnNamingLauncher` |
| `platform/api/clue_api/conversation_turns.py` | engine takes `namer`; starts it after the reply; grace before the terminal event |
| `platform/api/clue_api/agent_turn_fleet_wiring.py`, `fleet_main.py` | thread `namer` through composition |
| `platform/api/clue_api/chat/router.py`, `chat/schemas.py` | untitled Home thread; replay check; nullable wire title |
| `apps/frontend/src/features/projects/model/project-workspace.ts`, `data/project-home.repository.ts` | nullable bootstrap thread title |
| `apps/frontend/src/features/projects/hooks/use-naming-catch-up.ts` (new), `use-project-chat-controller.ts`, `components/project-workspace-shell.tsx` | bounded catch-up poll |
| `apps/frontend/docs/api-contracts/projects.md` | contract §4 rewritten |
| tests: `tests/clue_spine/test_project_naming_db.py`, `tests/api/test_thread_naming_store_db.py`, `tests/api/test_conversation_naming.py`, `tests/api/test_conversation_naming_db.py`, `tests/api/test_o6_conversation_composition_db.py` (one new test), `tests/api/test_home_project_bootstrap_db.py`, frontend `*.test.ts` | |

---

### Task 1: The untitled sentinel and the conditional project rename (clue_spine)

**Files:**
- Modify: `libs/clue-spine/clue_spine/spine.py` (after `set_project_name`, ~line 384)
- Modify: `libs/clue-spine/clue_spine/__init__.py` (import + `__all__`)
- Test: `tests/clue_spine/test_project_naming_db.py` (new)

**Interfaces:**
- Produces: `UNTITLED_PROJECT_NAME: str`; `async def set_project_name_if_untitled(conn, *, workspace_id: str, project_id: str, name: str) -> Project | None` (the row when the placeholder was replaced, `None` when the project was already named or does not exist in this workspace).

- [ ] **Step 1: Write the failing test**

```python
# tests/clue_spine/test_project_naming_db.py
"""Conversation naming — the conditional project rename fills only the placeholder."""

from __future__ import annotations

from clue_spine import (
    UNTITLED_PROJECT_NAME,
    get_project,
    set_project_name,
    set_project_name_if_untitled,
)
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


def test_untitled_sentinel_is_the_router_literal() -> None:
    assert UNTITLED_PROJECT_NAME == "Untitled project"


def test_conditional_rename_fills_only_the_placeholder(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        import pytest

        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            untitled = await seed_project(conn, "ws-naming-spine", name=UNTITLED_PROJECT_NAME)
            renamed = await set_project_name_if_untitled(
                conn,
                workspace_id="ws-naming-spine",
                project_id=untitled.project_id,
                name="GI practice outreach",
            )
            assert renamed is not None and renamed.name == "GI practice outreach"

            # A second generated name never overwrites the first.
            again = await set_project_name_if_untitled(
                conn,
                workspace_id="ws-naming-spine",
                project_id=untitled.project_id,
                name="Something else",
            )
            assert again is None
            assert (await get_project(conn, untitled.project_id)).name == "GI practice outreach"

            # A human rename wins: the manual writer is unconditional, the generated one is not.
            manual = await seed_project(conn, "ws-naming-spine", name=UNTITLED_PROJECT_NAME)
            await set_project_name(
                conn, workspace_id="ws-naming-spine", project_id=manual.project_id, name="Mine"
            )
            assert (
                await set_project_name_if_untitled(
                    conn, workspace_id="ws-naming-spine", project_id=manual.project_id, name="Bot"
                )
            ) is None
            assert (await get_project(conn, manual.project_id)).name == "Mine"

            # Cross-workspace: a miss, never a write.
            assert (
                await set_project_name_if_untitled(
                    conn, workspace_id="ws-other", project_id=untitled.project_id, name="X"
                )
            ) is None

    run_async(scenario())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/clue_spine/test_project_naming_db.py -p no:cacheprovider -v`
Expected: FAIL with `ImportError: cannot import name 'UNTITLED_PROJECT_NAME'`.

- [ ] **Step 3: Implement**

In `libs/clue-spine/clue_spine/spine.py`, above `create_project` (near `_PROJECT_COLUMNS`):

```python
#: The name a Home-created project is born with until the conversation namer replaces it (spec
#: 2026-09-18-conversation-naming-design §4.5). One constant: the router births it, the namer's
#: conditional rename matches on it, and the frontend's bootstrap schema pins the same literal.
UNTITLED_PROJECT_NAME = "Untitled project"
```

After `set_project_name`:

```python
async def set_project_name_if_untitled(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, name: str
) -> Project | None:
    """Replace the untitled placeholder with a generated name — and only the placeholder.

    The ``name = UNTITLED_PROJECT_NAME`` predicate is the whole manual-wins rule: a human rename
    that landed first turns this into a zero-row no-op, which the caller reads as ``None``.
    """
    result = await conn.execute(
        text(
            "UPDATE project SET name = :name "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            "AND name = :placeholder "
            f"RETURNING {_PROJECT_COLUMNS}"
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "name": name,
            "placeholder": UNTITLED_PROJECT_NAME,
        },
    )
    row = result.mappings().first()
    return Project(**dict(row)) if row is not None else None
```

In `libs/clue-spine/clue_spine/__init__.py` add `UNTITLED_PROJECT_NAME` and `set_project_name_if_untitled` to both the import block and `__all__` (next to `set_project_name`).

- [ ] **Step 4: Run the test to verify it passes**

Run: same command. Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/clue-spine/clue_spine/spine.py libs/clue-spine/clue_spine/__init__.py tests/clue_spine/test_project_naming_db.py
git commit -m "feat(spine): untitled-project sentinel and conditional generated rename

set_project_name_if_untitled replaces only the placeholder, so a human rename can never be
overwritten by the conversation namer (spec 2026-09-18-conversation-naming-design §4.5)."
```

---

### Task 2: The conditional thread title (thread_store)

**Files:**
- Modify: `platform/api/clue_api/thread_store.py` (after `set_thread_title`, ~line 284; `__all__` ~line 44)
- Test: `tests/api/test_thread_naming_store_db.py` (new)

**Interfaces:**
- Produces: `async def set_thread_title_if_unset(conn, *, workspace_id: str, thread_id: str, title: str) -> AgentThreadRow | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_thread_naming_store_db.py
"""Conversation naming — the conditional thread title fills only a null title."""

from __future__ import annotations

from uuid import uuid4

import pytest

from clue_api.thread_store import (
    create_thread,
    get_thread,
    set_thread_title,
    set_thread_title_if_unset,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


def test_conditional_title_fills_only_a_null_title(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"ws-naming-{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="Named project")
            principal = await seed_principal(
                conn, workspace_id=workspace_id, user_id="usr-naming", membership_id="mem-naming"
            )
            untitled = await create_thread(
                conn,
                thread_id=f"thr-naming-{uuid4().hex[:8]}",
                workspace_id=workspace_id,
                project_id=project.project_id,
                created_by_user_id=principal.user_id,
                created_via_membership_id=principal.membership_id,
            )
            assert untitled.title is None

            first = await set_thread_title_if_unset(
                conn, workspace_id=workspace_id, thread_id=untitled.id, title="Find GI accounts"
            )
            assert first is not None and first.title == "Find GI accounts"
            assert first.updated_at >= untitled.updated_at

            second = await set_thread_title_if_unset(
                conn, workspace_id=workspace_id, thread_id=untitled.id, title="Other"
            )
            assert second is None
            assert (await get_thread(conn, workspace_id=workspace_id, thread_id=untitled.id)).title == "Find GI accounts"

            manual = await create_thread(
                conn,
                thread_id=f"thr-manual-{uuid4().hex[:8]}",
                workspace_id=workspace_id,
                project_id=project.project_id,
                created_by_user_id=principal.user_id,
                created_via_membership_id=principal.membership_id,
            )
            await set_thread_title(conn, workspace_id=workspace_id, thread_id=manual.id, title="Mine")
            assert (
                await set_thread_title_if_unset(
                    conn, workspace_id=workspace_id, thread_id=manual.id, title="Bot"
                )
            ) is None

            assert (
                await set_thread_title_if_unset(
                    conn, workspace_id="ws-other", thread_id=untitled.id, title="X"
                )
            ) is None

    run_async(scenario())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_thread_naming_store_db.py -p no:cacheprovider -v`
Expected: FAIL with `ImportError: cannot import name 'set_thread_title_if_unset'`.

- [ ] **Step 3: Implement**

In `platform/api/clue_api/thread_store.py`, after `set_thread_title`:

```python
async def set_thread_title_if_unset(
    conn: AsyncConnection, *, workspace_id: str, thread_id: str, title: str
) -> AgentThreadRow | None:
    """Give an untitled thread its generated title — and only an untitled one.

    ``title IS NULL`` is the manual-wins rule (spec 2026-09-18-conversation-naming-design §4.5):
    a rename that landed first makes this a zero-row no-op, reported as ``None``. Not routed
    through :func:`_update` because that helper has no room for an extra predicate.
    """

    row = (
        (
            await conn.execute(
                text(
                    "UPDATE agent_thread SET title = :title, updated_at = now() "
                    "WHERE id = :id AND workspace_id = :workspace_id AND title IS NULL "
                    f"RETURNING {_COLUMNS}"
                ),
                {"id": thread_id, "workspace_id": workspace_id, "title": title},
            )
        )
        .mappings()
        .one_or_none()
    )
    return AgentThreadRow.model_validate(dict(row)) if row is not None else None
```

Add `"set_thread_title_if_unset",` to `__all__` after `"set_thread_title",`.

- [ ] **Step 4: Run the test to verify it passes**

Run: same command. Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/thread_store.py tests/api/test_thread_naming_store_db.py
git commit -m "feat(thread-store): conditional generated thread title

set_thread_title_if_unset writes only into a null title, so the namer can never overwrite a
human rename (spec 2026-09-18-conversation-naming-design §4.5)."
```

---

### Task 3: The three settings, with env parity

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after `arv2_display_client_pitch`, ~line 498)
- Modify: `.env.example` (after the `CLUE_ARV2_DISPLAY_CLIENT_PITCH` line, ~line 234)
- Modify: `.env` (after `CLUE_ARV2_DISPLAY_TIMEOUT_S`, ~line 363)
- Test: `tests/api/test_conversation_naming.py` (new; grows in Task 4)

**Interfaces:**
- Produces: `Settings.conversation_naming_enabled: bool = True`, `Settings.conversation_naming_model: str = "openai/gpt-5.6-luna"`, `Settings.conversation_naming_timeout_s: float = 60.0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_conversation_naming.py
"""Conversation naming — the pure parts: settings, the name normaliser, the prompt."""

from __future__ import annotations

import pytest

from clue_config import Settings


def test_naming_settings_default_on_luna_sixty_seconds() -> None:
    settings = Settings(_env_file=None)
    assert settings.conversation_naming_enabled is True
    assert settings.conversation_naming_model == "openai/gpt-5.6-luna"
    assert settings.conversation_naming_timeout_s == 60.0


def test_naming_settings_read_their_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_CONVERSATION_NAMING_ENABLED", "false")
    monkeypatch.setenv("CLUE_CONVERSATION_NAMING_MODEL", "openai/gpt-5-mini")
    monkeypatch.setenv("CLUE_CONVERSATION_NAMING_TIMEOUT_S", "12.5")
    settings = Settings(_env_file=None)
    assert settings.conversation_naming_enabled is False
    assert settings.conversation_naming_model == "openai/gpt-5-mini"
    assert settings.conversation_naming_timeout_s == 12.5


def test_env_example_and_lane_env_carry_the_three_knobs() -> None:
    for path in (".env.example", ".env"):
        body = open(path, encoding="utf-8").read()
        assert "CLUE_CONVERSATION_NAMING_ENABLED=true" in body, path
        assert "CLUE_CONVERSATION_NAMING_MODEL=openai/gpt-5.6-luna" in body, path
        assert "CLUE_CONVERSATION_NAMING_TIMEOUT_S=60.0" in body, path
```

- [ ] **Step 2: Run it to verify it fails**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_conversation_naming.py -p no:cacheprovider -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'conversation_naming_enabled'` (the first two) and the assertion on `.env.example` (the third).

- [ ] **Step 3: Implement**

`libs/clue-config/clue_config/settings.py`, after the `arv2_display_client_pitch` block:

```python
    # --- Conversation naming (spec 2026-09-18-conversation-naming-design §4.8) ---------------
    # One cheap call names the chat (and, on the Home path, the project) once the first agent
    # reply exists. Off keeps the placeholders. Env: ``CLUE_CONVERSATION_NAMING_ENABLED``.
    conversation_naming_enabled: bool = True
    # OpenRouter model id for the naming call. Env: ``CLUE_CONVERSATION_NAMING_MODEL``.
    conversation_naming_model: str = "openai/gpt-5.6-luna"
    # The naming call's HTTP timeout. The turn never waits this long — the engine waits
    # ``NAMING_GRACE_S`` and lets a slower call finish detached (§4.1).
    # Env: ``CLUE_CONVERSATION_NAMING_TIMEOUT_S``.
    conversation_naming_timeout_s: float = 60.0
```

`.env.example`, after the `CLUE_ARV2_DISPLAY_CLIENT_PITCH` line:

```
# --- Conversation naming (chat titles and project names after the first reply) --------
# One cheap call names the chat (and, on the Home path, the project) once the first agent
# reply exists. Off = placeholders stay ("Untitled project" / "New chat").
CLUE_CONVERSATION_NAMING_ENABLED=true
# OpenRouter model id for the naming call.
CLUE_CONVERSATION_NAMING_MODEL=openai/gpt-5.6-luna
# Call timeout in seconds. The turn never waits this long (see NAMING_GRACE_S in
# platform/api/clue_api/conversation_naming.py).
CLUE_CONVERSATION_NAMING_TIMEOUT_S=60.0
```

`.env` (the lane file, git-ignored), after `CLUE_ARV2_DISPLAY_TIMEOUT_S=240.0`: the same three `KEY=value` lines (comments optional).

- [ ] **Step 4: Run the test to verify it passes**

Run: same command. Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/clue-config/clue_config/settings.py .env.example tests/api/test_conversation_naming.py
git commit -m "feat(config): conversation naming settings — enabled, model, timeout

CLUE_CONVERSATION_NAMING_ENABLED=true / _MODEL=openai/gpt-5.6-luna / _TIMEOUT_S=60.0, in
.env.example per the parity rule (spec 2026-09-18-conversation-naming-design §4.8)."
```

---

### Task 4: The pure half of the namer — normaliser, prompt, request/outcome types

**Files:**
- Create: `platform/api/clue_api/conversation_naming.py`
- Test: `tests/api/test_conversation_naming.py` (append)

**Interfaces:**
- Produces (all in `clue_api.conversation_naming`):
  - constants `NAMING_GRACE_S`, `NAMING_INPUT_CHARS`, `NAMING_MAX_TOKENS`, `NAMING_MAX_CODE_POINTS`, `NAMING_MAX_WORDS`, `NAMING_LABEL`, `NAMING_SYSTEM_PROMPT`, `NAMING_RESPONSE_FORMAT`, `PLACEHOLDER_NAMES`
  - `def normalize_generated_name(raw: object) -> str | None`
  - `def build_naming_messages(*, brand_name: str, product_name: str | None, project_name: str | None, needs_chat_title: bool, needs_project_name: bool, user_message: str, assistant_message: str) -> list[dict[str, str]]`
  - `@dataclass(frozen=True, slots=True) class NamingRequest(workspace_id: str, project_id: str, thread_id: str, turn_id: UUID, user_message: str, assistant_message: str)`
  - `@dataclass(frozen=True, slots=True) class NamingOutcome(chat_title: str | None, project_name: str | None, skipped_reason: str | None)`
  - `class ConversationNamer(Protocol): async def name(self, request: NamingRequest) -> NamingOutcome`

- [ ] **Step 1: Write the failing tests (append to `tests/api/test_conversation_naming.py`)**

```python
from clue_api.conversation_naming import (
    NAMING_INPUT_CHARS,
    NAMING_RESPONSE_FORMAT,
    NAMING_SYSTEM_PROMPT,
    build_naming_messages,
    normalize_generated_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Find GI target accounts", "Find GI target accounts"),
        ('  "Find  GI\ttarget accounts."  ', "Find GI target accounts"),
        ("“Outreach to GI groups!”", "Outreach to GI groups"),
        ("Plan the Q4 push…", "Plan the Q4 push"),
        ("", None),
        ("   ", None),
        ("Untitled project", None),
        ("new chat", None),
        ("one two three four five six seven eight nine", None),
        ("x" * 61, None),
        (42, None),
        (None, None),
    ],
)
def test_normalize_generated_name(raw: object, expected: str | None) -> None:
    assert normalize_generated_name(raw) == expected


def test_prompt_states_the_rules_the_spec_fixed() -> None:
    for phrase in (
        "2 to 5 words",
        "language the user wrote in",
        "Sentence case",
        "Never repeat the project name inside the chat title",
        "Never invent company, product or segment names",
        "empty string",
    ):
        assert phrase in NAMING_SYSTEM_PROMPT, phrase
    schema = NAMING_RESPONSE_FORMAT["json_schema"]["schema"]
    assert set(schema["properties"]) == {"chat_title", "project_name"}
    assert schema["additionalProperties"] is False


def test_messages_carry_only_what_is_known_and_bound_the_exchange() -> None:
    messages = build_naming_messages(
        brand_name="Acme Health",
        product_name=None,
        project_name=None,
        needs_chat_title=True,
        needs_project_name=True,
        user_message="u" * (NAMING_INPUT_CHARS + 50),
        assistant_message="a" * (NAMING_INPUT_CHARS + 50),
    )
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == NAMING_SYSTEM_PROMPT
    body = messages[1]["content"]
    assert "Brand: Acme Health" in body
    assert "Product:" not in body
    assert "Project:" not in body
    assert "Needed: chat_title, project_name" in body
    assert body.count("u") == NAMING_INPUT_CHARS
    assert body.count("a" * 10) == NAMING_INPUT_CHARS // 10

    named = build_naming_messages(
        brand_name="Acme Health",
        product_name="Aura",
        project_name="GI practice outreach",
        needs_chat_title=True,
        needs_project_name=False,
        user_message="Who should we target first?",
        assistant_message="Start with GI groups in Texas.",
    )
    body = named[1]["content"]
    assert "Product: Aura" in body
    assert "Project: GI practice outreach" in body
    assert "Needed: chat_title" in body and "project_name" not in body.split("Needed:")[1].split("\n")[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_conversation_naming.py -p no:cacheprovider -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clue_api.conversation_naming'`.

- [ ] **Step 3: Create the module (pure half)**

```python
# platform/api/clue_api/conversation_naming.py
"""Conversation naming — one cheap call names a chat and, on the Home path, its project.

Spec: docs/superpowers/specs/archive/2026-09-18-conversation-naming-design.md. The namer is a service
step with no agent authority: it is not a tool, appears in no profile, and never raises into the
turn that started it. It fills only placeholders — ``agent_thread.title IS NULL`` and
``project.name = UNTITLED_PROJECT_NAME`` — so a human rename always wins (§4.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from clue_obs import get_logger

log = get_logger("clue_api.conversation_naming")

#: How long the engine waits for the namer before emitting the terminal turn event (§4.1). NOT
#: the call timeout: a slower call keeps running detached and writes its names when it lands.
NAMING_GRACE_S = 3.0
#: Prefix of the user message and of the reply the prompt sees (§4.2).
NAMING_INPUT_CHARS = 2_000
NAMING_MAX_TOKENS = 60
NAMING_MAX_CODE_POINTS = 60
NAMING_MAX_WORDS = 8
NAMING_LABEL = "conversation_naming"
NAMING_ESTIMATE_USD = Decimal("0.001")
#: Names the model may not hand back (case-folded).
PLACEHOLDER_NAMES = frozenset({"untitled project", "new chat", "untitled"})

NAMING_SYSTEM_PROMPT = """You name conversations for a B2B account-based-marketing workspace.
You are given the first exchange of a chat and asked for one or two names.

chat_title: 2 to 5 words naming the task the user is doing in this chat.
project_name: 2 to 5 words naming the overall marketing motion this project
is about — who is being targeted, for what, or with what product. Only when asked.

Rules:
- Write in the language the user wrote in.
- Sentence case. No trailing punctuation, no quotes, no emoji, no hashtags.
- Never repeat the project name inside the chat title.
- Never invent company, product or segment names that do not appear in the exchange;
  when the exchange names an account or a segment, prefer it.
- If a field is not listed under Needed, return an empty string for it.
- Return only the JSON object."""

NAMING_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "conversation_names",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "chat_title": {"type": "string"},
                "project_name": {"type": "string"},
            },
            "required": ["chat_title", "project_name"],
            "additionalProperties": False,
        },
    },
}

_WRAPPING = "\"'`“”‘’"
_TRAILING = ".!?:;,…"


def normalize_generated_name(raw: object) -> str | None:
    """One generated name, cleaned — or ``None`` when it must be dropped (§4.4).

    Dropped, never truncated: a bad output leaves the placeholder rather than a mangled title.
    """
    if not isinstance(raw, str):
        return None
    text = " ".join(raw.split())
    text = text.strip(_WRAPPING).strip()
    text = text.rstrip(_TRAILING).strip()
    if not text:
        return None
    if len(text) > NAMING_MAX_CODE_POINTS or len(text.split()) > NAMING_MAX_WORDS:
        return None
    if text.casefold() in PLACEHOLDER_NAMES:
        return None
    return text


def build_naming_messages(
    *,
    brand_name: str,
    product_name: str | None,
    project_name: str | None,
    needs_chat_title: bool,
    needs_project_name: bool,
    user_message: str,
    assistant_message: str,
) -> list[dict[str, str]]:
    """The two chat messages of one naming call (§4.2, §4.3)."""
    needed = [
        field
        for field, wanted in (("chat_title", needs_chat_title), ("project_name", needs_project_name))
        if wanted
    ]
    lines = [f"Brand: {brand_name}"]
    if product_name:
        lines.append(f"Product: {product_name}")
    if project_name:
        lines.append(f"Project: {project_name}")
    lines.append(f"Needed: {', '.join(needed)}")
    lines.append("")
    lines.append("User wrote:")
    lines.append(user_message[:NAMING_INPUT_CHARS])
    lines.append("")
    lines.append("Assistant replied:")
    lines.append(assistant_message[:NAMING_INPUT_CHARS])
    return [
        {"role": "system", "content": NAMING_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


@dataclass(frozen=True, slots=True)
class NamingRequest:
    """What the engine hands the namer: the turn's scope and its opening exchange."""

    workspace_id: str
    project_id: str
    thread_id: str
    turn_id: UUID
    user_message: str
    assistant_message: str


@dataclass(frozen=True, slots=True)
class NamingOutcome:
    """What landed. ``skipped_reason`` is set when nothing was written (§4.10)."""

    chat_title: str | None
    project_name: str | None
    skipped_reason: str | None


class ConversationNamer(Protocol):
    async def name(self, request: NamingRequest) -> NamingOutcome: ...
```

(The rest of the module — `OpenRouterConversationNamer`, `build_conversation_namer`, `TurnNamingLauncher` — is added in Tasks 5 and 6, each with the imports it needs.)

- [ ] **Step 4: Run to verify it passes**

Run: same command. Expected: all tests in the file pass. Also `uv run ruff check platform/api/clue_api/conversation_naming.py`.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/conversation_naming.py tests/api/test_conversation_naming.py
git commit -m "feat(naming): conversation naming pure half — normaliser, prompt, request types

normalize_generated_name drops (never truncates) a bad name; build_naming_messages carries
brand/product/project context and the bounded opening exchange (spec §4.2–§4.4)."
```

---

### Task 5: `OpenRouterConversationNamer` — the metered call and the conditional writes

**Files:**
- Modify: `platform/api/clue_api/conversation_naming.py` (append)
- Test: `tests/api/test_conversation_naming_db.py` (new)

**Interfaces:**
- Consumes: Task 1 `UNTITLED_PROJECT_NAME`, `set_project_name_if_untitled`; Task 2 `set_thread_title_if_unset`; Task 3 settings; Task 4 types.
- Produces: `class OpenRouterConversationNamer(api_key: SecretStr, base_url: str, model: str, timeout_s: float, artifacts: ArtifactSink | None, conn_factory: ConnFactory = transaction, transport_factory: Callable[[], Transport] = HttpxTransport)` with `async def name(request) -> NamingOutcome`; `def build_conversation_namer(*, settings: Settings, secrets: Secrets, artifacts: ArtifactSink | None, conn_factory: ConnFactory = transaction) -> ConversationNamer | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_conversation_naming_db.py
"""Conversation naming — the metered call writes only placeholders and always drains its spend."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.conversation_naming import (
    NAMING_LABEL,
    NamingRequest,
    OpenRouterConversationNamer,
)
from clue_api.thread_store import create_thread, get_thread, set_thread_title
from clue_spend.transport import HttpResponse, ScriptedTransport, TransportFailure
from clue_spine import UNTITLED_PROJECT_NAME, get_project
from pydantic import SecretStr
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


def _reply(chat_title: str, project_name: str) -> HttpResponse:
    body = {
        "choices": [
            {"message": {"content": json.dumps({"chat_title": chat_title, "project_name": project_name})}}
        ],
        "usage": {"prompt_tokens": 250, "completion_tokens": 12, "cost": 0.00006},
    }
    return HttpResponse(status=200, headers={"content-type": "application/json"}, body=json.dumps(body).encode())


def _namer(conn, script: list[HttpResponse | TransportFailure]) -> tuple[OpenRouterConversationNamer, ScriptedTransport]:
    transport = ScriptedTransport(script)
    namer = OpenRouterConversationNamer(
        api_key=SecretStr("test-key"),
        base_url="https://openrouter.invalid/api/v1",
        model="openai/gpt-5.6-luna",
        timeout_s=60.0,
        artifacts=None,
        conn_factory=conn_session_factory(conn),
        transport_factory=lambda: transport,
    )
    return namer, transport


async def _scope(conn, *, project_name: str, thread_title: str | None = None):
    workspace_id = f"ws-namer-{uuid4().hex[:8]}"
    project = await seed_project(conn, workspace_id, name=project_name)
    principal = await seed_principal(
        conn, workspace_id=workspace_id, user_id="usr-namer", membership_id="mem-namer"
    )
    thread = await create_thread(
        conn,
        thread_id=f"thr-namer-{uuid4().hex[:8]}",
        workspace_id=workspace_id,
        project_id=project.project_id,
        title=thread_title,
        created_by_user_id=principal.user_id,
        created_via_membership_id=principal.membership_id,
    )
    return workspace_id, project, thread


def _request(workspace_id: str, project_id: str, thread_id: str) -> NamingRequest:
    return NamingRequest(
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=thread_id,
        turn_id=uuid4(),
        user_message="Which GI practices in Texas should we go after first?",
        assistant_message="Start with the independent GI groups in Dallas and Houston.",
    )


async def _ledger_rows(conn, turn_id) -> list[dict]:
    rows = (
        await conn.execute(
            text(
                "SELECT label, phase, outcome, project_id FROM provider_call_ledger "
                "WHERE job_id = :job ORDER BY recorded_at"
            ),
            {"job": turn_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def test_home_path_names_both_and_drains_the_ledger(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, project, thread = await _scope(conn, project_name=UNTITLED_PROJECT_NAME)
            namer, transport = _namer(conn, [_reply("Find GI target accounts", "GI practice outreach")])
            request = _request(workspace_id, project.project_id, thread.id)

            outcome = await namer.name(request)

            assert outcome.skipped_reason is None
            assert outcome.chat_title == "Find GI target accounts"
            assert outcome.project_name == "GI practice outreach"
            assert (await get_thread(conn, workspace_id=workspace_id, thread_id=thread.id)).title == "Find GI target accounts"
            assert (await get_project(conn, project.project_id)).name == "GI practice outreach"

            sent = json.loads(transport.requests[0].body)
            assert sent["model"] == "openai/gpt-5.6-luna"
            assert sent["reasoning"] == {"effort": "none"}
            assert sent["max_tokens"] == 60
            assert "Needed: chat_title, project_name" in sent["messages"][1]["content"]

            rows = await _ledger_rows(conn, request.turn_id)
            assert [row["label"] for row in rows] == [NAMING_LABEL, NAMING_LABEL]
            assert rows[-1]["phase"] == "result"
            assert rows[-1]["project_id"] == project.project_id

    run_async(scenario())


def test_named_project_asks_only_for_the_chat_title(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, project, thread = await _scope(conn, project_name="GI practice outreach")
            namer, transport = _namer(conn, [_reply("Texas GI shortlist", "")])

            outcome = await namer.name(_request(workspace_id, project.project_id, thread.id))

            assert outcome == type(outcome)(chat_title="Texas GI shortlist", project_name=None, skipped_reason=None)
            body = json.loads(transport.requests[0].body)["messages"][1]["content"]
            assert "Project: GI practice outreach" in body
            assert "Needed: chat_title\n" in body
            assert (await get_project(conn, project.project_id)).name == "GI practice outreach"

    run_async(scenario())


def test_already_named_thread_and_project_make_no_call(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, project, thread = await _scope(conn, project_name="Named", thread_title="Mine")
            namer, transport = _namer(conn, [])
            outcome = await namer.name(_request(workspace_id, project.project_id, thread.id))
            assert outcome.skipped_reason == "already_named"
            assert transport.requests == []

    run_async(scenario())


def test_manual_rename_during_the_call_wins(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, project, thread = await _scope(conn, project_name=UNTITLED_PROJECT_NAME)
            namer, _ = _namer(conn, [_reply("Bot title", "Bot project")])
            # A human title present at call time means the chat slot is not asked for and never
            # written, while the still-untitled project is. The narrower race (the namer READ a
            # null title, the rename landed before its conditional write) is decided by the WHERE
            # clause and is pinned by tests/api/test_thread_naming_store_db.py.
            await set_thread_title(conn, workspace_id=workspace_id, thread_id=thread.id, title="Mine")
            outcome = await namer.name(_request(workspace_id, project.project_id, thread.id))
            assert outcome.chat_title is None
            assert outcome.project_name == "Bot project"
            assert (await get_thread(conn, workspace_id=workspace_id, thread_id=thread.id)).title == "Mine"

    run_async(scenario())


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ([TransportFailure("connection reset")], "provider_error"),
        ([HttpResponse(status=500, body=b"{}")], "provider_error"),
        ([HttpResponse(status=200, body=b'{"choices":[{"message":{"content":"not json"}}]}')], "invalid_reply"),
        ([_reply("", "")], "names_rejected"),
        ([_reply("one two three four five six seven eight nine", "Untitled project")], "names_rejected"),
    ],
)
def test_failures_skip_loudly_and_leave_placeholders(migrated_db: bool, script, reason) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, project, thread = await _scope(conn, project_name=UNTITLED_PROJECT_NAME)
            namer, _ = _namer(conn, list(script))
            request = _request(workspace_id, project.project_id, thread.id)
            outcome = await namer.name(request)
            assert outcome.skipped_reason == reason
            assert (await get_thread(conn, workspace_id=workspace_id, thread_id=thread.id)).title is None
            assert (await get_project(conn, project.project_id)).name == UNTITLED_PROJECT_NAME
            # Money trail is complete even when nothing was written.
            assert await _ledger_rows(conn, request.turn_id)

    run_async(scenario())
```

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_conversation_naming_db.py -p no:cacheprovider -v`
Expected: FAIL with `ImportError: cannot import name 'OpenRouterConversationNamer'`.

- [ ] **Step 3: Implement (append to `conversation_naming.py`)**

Add these imports to the module's import block first:

```python
import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from clue_api.arv2.errors import RawParseError
from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_api.thread_store import get_thread, set_thread_title_if_unset
from clue_config import Secrets, Settings
from clue_config.gateway import GatewayConfig
from clue_db import ConnFactory, transaction
from clue_obs import observation
from clue_spend.calls import CallResult, CallSpec, ProviderCaller, SpendEstimate
from clue_spend.ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_spend.transport import HttpxTransport, Transport
from clue_spine import (
    UNTITLED_PROJECT_NAME,
    get_brand,
    get_product,
    get_project_for_workspace,
    set_project_name_if_untitled,
)
```

Then append:

```python
class _NamesReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chat_title: str = ""
    project_name: str = ""


def _read_names(result: CallResult) -> _NamesReply | None:
    """The reply as the two names, or ``None`` when the model did not answer in shape."""
    try:
        return _NamesReply.model_validate(json.loads(openrouter_message_text(result.json())))
    except (RawParseError, ValueError, ValidationError):
        return None


class OpenRouterConversationNamer:
    """The production namer: one OpenRouter call through the spend-ledger caller (§4.2, §4.9)."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_s: float,
        artifacts: ArtifactSink | None,
        conn_factory: ConnFactory = transaction,
        transport_factory: Callable[[], Transport] = HttpxTransport,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout_s = timeout_s
        self._artifacts = artifacts
        self._conn_factory = conn_factory
        self._transport_factory = transport_factory

    async def name(self, request: NamingRequest) -> NamingOutcome:
        """Never raises: every failure is one ``conversation_naming.skipped`` event (§4.10)."""
        try:
            return await self._name(request)
        except Exception:  # noqa: BLE001 — a naming failure must never reach the turn
            log.warning(
                "conversation_naming.skipped",
                reason="unexpected_error",
                turn_id=str(request.turn_id),
                thread_id=request.thread_id,
                project_id=request.project_id,
                exc_info=True,
            )
            return NamingOutcome(chat_title=None, project_name=None, skipped_reason="unexpected_error")

    async def _name(self, request: NamingRequest) -> NamingOutcome:
        async with self._conn_factory() as conn:
            thread = await get_thread(
                conn, workspace_id=request.workspace_id, thread_id=request.thread_id
            )
            project = await get_project_for_workspace(
                conn, workspace_id=request.workspace_id, project_id=request.project_id
            )
            if thread is None or project is None:
                return self._skip(request, "scope_missing")
            needs_chat_title = thread.title is None
            needs_project_name = project.name == UNTITLED_PROJECT_NAME
            if not (needs_chat_title or needs_project_name):
                return self._skip(request, "already_named", level="info")
            brand = await get_brand(conn, workspace_id=request.workspace_id, brand_id=project.brand_id)
            product = (
                await get_product(conn, project.product_id) if project.product_id is not None else None
            )

        messages = build_naming_messages(
            brand_name=brand.name if brand is not None else "",
            product_name=product.name if product is not None else None,
            project_name=None if needs_project_name else project.name,
            needs_chat_title=needs_chat_title,
            needs_project_name=needs_project_name,
            user_message=request.user_message,
            assistant_message=request.assistant_message,
        )
        spec = CallSpec(
            provider="openrouter",
            operation="chat/completions",
            label=NAMING_LABEL,
            request=openrouter_chat_request(
                base_url=self._base_url,
                api_key=self._api_key,
                model=self._model,
                messages=messages,
                response_format=NAMING_RESPONSE_FORMAT,
                reasoning={"effort": "none"},
                max_tokens=NAMING_MAX_TOKENS,
                temperature=0.2,
                timeout_s=self._timeout_s,
            ),
            estimate=SpendEstimate(usd=NAMING_ESTIMATE_USD),
            max_attempts=1,
            cost_reader=openrouter_cost_reader,
            halt_rule=openrouter_halt_rule,
            extras={
                "thread_id": request.thread_id,
                "project_id": request.project_id,
                "turn_id": str(request.turn_id),
            },
        )
        raw, ledger = BufferedRawSink(), BufferedLedger()
        caller = ProviderCaller(
            transport=self._transport_factory(),
            raw_sink=raw,
            ledger=ledger,
            now=lambda: datetime.now(UTC),
        )
        reason: str | None = None
        chat_title: str | None = None
        project_name: str | None = None
        try:
            with observation(
                "conversation.naming",
                as_type="generation",
                model=self._model,
                input={"needs_chat_title": needs_chat_title, "needs_project_name": needs_project_name},
            ) as current:
                try:
                    # ``ProviderCaller.call`` is synchronous (httpx); keep the worker loop free.
                    result = await asyncio.to_thread(caller.call, spec)
                except Exception:  # noqa: BLE001 — recorded as a skip, never raised
                    log.warning("conversation_naming.call_failed", turn_id=str(request.turn_id), exc_info=True)
                    reason = "provider_error"
                else:
                    if result.response.status >= 400:
                        reason = "provider_error"
                    else:
                        reply = _read_names(result)
                        if reply is None:
                            reason = "invalid_reply"
                        else:
                            chat_title = (
                                normalize_generated_name(reply.chat_title) if needs_chat_title else None
                            )
                            project_name = (
                                normalize_generated_name(reply.project_name)
                                if needs_project_name
                                else None
                            )
                            if chat_title is None and project_name is None:
                                reason = "names_rejected"
                current.update(
                    output={"chat_title": chat_title, "project_name": project_name},
                    level="DEFAULT" if reason is None else "WARNING",
                    status_message=reason,
                )
        finally:
            async with self._conn_factory() as conn:
                await drain_provider_calls(
                    conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=self._artifacts,
                    stamp=LedgerStamp(
                        workspace_id=request.workspace_id,
                        project_id=request.project_id,
                        job_id=request.turn_id,
                    ),
                )
        if reason is not None:
            return self._skip(request, reason)

        applied_chat: str | None = None
        applied_project: str | None = None
        async with self._conn_factory() as conn:
            if chat_title is not None:
                row = await set_thread_title_if_unset(
                    conn, workspace_id=request.workspace_id, thread_id=request.thread_id, title=chat_title
                )
                if row is None:
                    log.info(
                        "conversation_naming.skipped",
                        reason="lost_to_manual_rename",
                        slot="chat_title",
                        turn_id=str(request.turn_id),
                        thread_id=request.thread_id,
                    )
                else:
                    applied_chat = chat_title
            if project_name is not None:
                project_row = await set_project_name_if_untitled(
                    conn,
                    workspace_id=request.workspace_id,
                    project_id=request.project_id,
                    name=project_name,
                )
                if project_row is None:
                    log.info(
                        "conversation_naming.skipped",
                        reason="lost_to_manual_rename",
                        slot="project_name",
                        turn_id=str(request.turn_id),
                        project_id=request.project_id,
                    )
                else:
                    applied_project = project_name
        log.info(
            "conversation_naming.applied",
            turn_id=str(request.turn_id),
            thread_id=request.thread_id,
            project_id=request.project_id,
            chat_title=applied_chat,
            project_name=applied_project,
        )
        return NamingOutcome(chat_title=applied_chat, project_name=applied_project, skipped_reason=None)

    @staticmethod
    def _skip(request: NamingRequest, reason: str, *, level: str = "warning") -> NamingOutcome:
        getattr(log, level)(
            "conversation_naming.skipped",
            reason=reason,
            turn_id=str(request.turn_id),
            thread_id=request.thread_id,
            project_id=request.project_id,
        )
        return NamingOutcome(chat_title=None, project_name=None, skipped_reason=reason)


def build_conversation_namer(
    *,
    settings: Settings,
    secrets: Secrets,
    artifacts: ArtifactSink | None,
    conn_factory: ConnFactory = transaction,
) -> ConversationNamer | None:
    """The fleet worker's namer, or ``None`` (stated once at boot) when off or keyless."""
    if not settings.conversation_naming_enabled:
        log.info("conversation_naming.not_composed", reason="CLUE_CONVERSATION_NAMING_ENABLED is off")
        return None
    key = secrets.openrouter_api_key
    if key is None or not key.get_secret_value().strip():
        log.warning(
            "conversation_naming.not_composed",
            reason="CLUE_OPENROUTER_API_KEY is not configured",
            detail="chats and projects keep their placeholder names on this worker",
        )
        return None
    return OpenRouterConversationNamer(
        api_key=key,
        base_url=GatewayConfig().base_url,
        model=settings.conversation_naming_model,
        timeout_s=settings.conversation_naming_timeout_s,
        artifacts=artifacts,
        conn_factory=conn_factory,
    )
```

Implementation notes: `CallResult.response.status` is the HTTP status (`clue_spend.transport.HttpResponse`). `result.json()` raises `RawParseError` on a non-JSON body. `ArtifactSink` is the protocol in `clue_spend.ledger` (`persist_body(workspace_id, data, media_type)`), which `DurableAgentArtifactStore` satisfies. If `ScriptedTransport` in the failure test returns a 500, confirm whether `ProviderCaller.call` raises or returns for a non-retried 5xx (`max_attempts=1`); both branches map to `provider_error`, so either behaviour passes.

- [ ] **Step 4: Run to verify it passes**

Run: same command; also re-run `tests/api/test_conversation_naming.py` and `uv run ruff check platform/api/clue_api/conversation_naming.py tests/api/test_conversation_naming_db.py`.
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/conversation_naming.py tests/api/test_conversation_naming_db.py
git commit -m "feat(naming): OpenRouterConversationNamer — one metered call, conditional writes

Reads the placeholder state, asks only for what is missing, drains every call onto the
provider ledger stamped with the turn, writes through the conditional store functions, and
turns every failure into one conversation_naming.skipped event (spec §4.2, §4.5, §4.9, §4.10)."
```

---

### Task 6: The turn hook — launcher, engine wiring, fleet composition

**Files:**
- Modify: `platform/api/clue_api/conversation_naming.py` (append `TurnNamingLauncher`)
- Modify: `platform/api/clue_api/conversation_turns.py` (`ConversationTurnEngine.__init__`, `execute`, `_result_from_outcome`, `_project_turn_close`, `build_conversation_turn_engine`)
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py` (`build_agent_turn_work_handler` gains `namer`)
- Modify: `platform/api/clue_api/fleet_main.py` (compose the namer under `settings.chat_enabled`)
- Test: `tests/api/test_conversation_naming.py` (launcher unit tests), `tests/api/test_o6_conversation_composition_db.py` (one new end-to-end test)

**Interfaces:**
- Consumes: Task 4/5 `ConversationNamer`, `NamingRequest`, `NAMING_GRACE_S`, `build_conversation_namer`.
- Produces: `class TurnNamingLauncher(namer: ConversationNamer | None, grace_s: float = NAMING_GRACE_S)` with `def start(self, request: NamingRequest) -> asyncio.Task[NamingOutcome] | None`, `async def wait_grace(self, task: asyncio.Task[NamingOutcome] | None) -> bool` (True when the task finished inside the grace), `@property pending: int`; `build_conversation_turn_engine(..., namer: ConversationNamer | None = None)`; `build_agent_turn_work_handler(..., namer: ConversationNamer | None = None)`.

- [ ] **Step 1: Write the failing launcher tests (append to `tests/api/test_conversation_naming.py`)**

```python
import asyncio
from uuid import uuid4

from clue_api.conversation_naming import NamingOutcome, NamingRequest, TurnNamingLauncher


def _naming_request() -> NamingRequest:
    return NamingRequest(
        workspace_id="ws",
        project_id="prj",
        thread_id="thr",
        turn_id=uuid4(),
        user_message="u",
        assistant_message="a",
    )


class _SlowNamer:
    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s
        self.calls: list[NamingRequest] = []

    async def name(self, request: NamingRequest) -> NamingOutcome:
        self.calls.append(request)
        await asyncio.sleep(self.delay_s)
        return NamingOutcome(chat_title="Fast title", project_name=None, skipped_reason=None)


def test_launcher_without_a_namer_starts_nothing() -> None:
    async def scenario() -> None:
        launcher = TurnNamingLauncher(namer=None)
        assert launcher.start(_naming_request()) is None
        assert await launcher.wait_grace(None) is True
        assert launcher.pending == 0

    asyncio.run(scenario())


def test_fast_namer_finishes_inside_the_grace() -> None:
    async def scenario() -> None:
        namer = _SlowNamer(0.01)
        launcher = TurnNamingLauncher(namer=namer, grace_s=0.5)
        task = launcher.start(_naming_request())
        assert task is not None
        assert await launcher.wait_grace(task) is True
        assert task.result().chat_title == "Fast title"
        assert launcher.pending == 0

    asyncio.run(scenario())


def test_slow_namer_is_left_running_detached_and_still_completes() -> None:
    async def scenario() -> None:
        namer = _SlowNamer(0.2)
        launcher = TurnNamingLauncher(namer=namer, grace_s=0.02)
        task = launcher.start(_naming_request())
        assert task is not None
        assert await launcher.wait_grace(task) is False
        assert not task.done()
        assert launcher.pending == 1
        await task
        assert task.result().chat_title == "Fast title"
        assert launcher.pending == 0

    asyncio.run(scenario())


def test_launcher_swallows_a_namer_that_raises() -> None:
    class _Broken:
        async def name(self, request: NamingRequest) -> NamingOutcome:
            raise RuntimeError("boom")

    async def scenario() -> None:
        launcher = TurnNamingLauncher(namer=_Broken(), grace_s=0.5)
        task = launcher.start(_naming_request())
        assert task is not None
        assert await launcher.wait_grace(task) is True
        assert task.result().skipped_reason == "unexpected_error"

    asyncio.run(scenario())
```

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_conversation_naming.py -p no:cacheprovider -v -k launcher`
Expected: FAIL with `ImportError: cannot import name 'TurnNamingLauncher'`.

- [ ] **Step 3: Implement the launcher (append to `conversation_naming.py`)**

```python
class TurnNamingLauncher:
    """Starts the namer beside the turn's close projection and bounds how long the turn waits.

    §4.1: the terminal turn event waits at most ``grace_s``; a slower call keeps running as a
    task this launcher holds a reference to (so it is neither garbage-collected nor awaited by
    the fleet handler) and writes its names when it lands. Worker shutdown cancels it — the
    placeholder stays and the next completed turn retries.
    """

    def __init__(self, *, namer: ConversationNamer | None, grace_s: float = NAMING_GRACE_S) -> None:
        self._namer = namer
        self._grace_s = grace_s
        self._pending: set[asyncio.Task[NamingOutcome]] = set()

    @property
    def pending(self) -> int:
        return len(self._pending)

    def start(self, request: NamingRequest) -> asyncio.Task[NamingOutcome] | None:
        if self._namer is None:
            return None
        namer = self._namer

        async def _run() -> NamingOutcome:
            try:
                return await namer.name(request)
            except Exception:  # noqa: BLE001 — a namer that raises is a skip, never a turn error
                log.warning(
                    "conversation_naming.skipped",
                    reason="unexpected_error",
                    turn_id=str(request.turn_id),
                    thread_id=request.thread_id,
                    exc_info=True,
                )
                return NamingOutcome(chat_title=None, project_name=None, skipped_reason="unexpected_error")

        task = asyncio.create_task(_run(), name=f"conversation-naming:{request.turn_id}")
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return task

    async def wait_grace(self, task: asyncio.Task[NamingOutcome] | None) -> bool:
        """``True`` when there was nothing to wait for or the namer finished inside the grace."""
        if task is None:
            return True
        done, _ = await asyncio.wait({task}, timeout=self._grace_s)
        if task in done:
            return True
        log.info("conversation_naming.detached", task=task.get_name(), grace_s=self._grace_s)
        return False
```

- [ ] **Step 4: Run the launcher tests to verify they pass**

Run: same command. Expected: 4 passed.

- [ ] **Step 5: Write the failing end-to-end test (append to `tests/api/test_o6_conversation_composition_db.py`)**

Add a `namer` parameter to that file's `_run_turn` helper and pass it through to `build_agent_turn_work_handler(..., namer=namer)`; default `None` so every existing test is untouched. Then:

```python
class _RecordingNamer:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def name(self, request: Any) -> Any:
        from clue_api.conversation_naming import NamingOutcome

        self.requests.append(request)
        return NamingOutcome(chat_title="Start with GI", project_name=None, skipped_reason=None)


def test_the_production_turn_hands_its_opening_exchange_to_the_namer(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with postgres_agent_checkpointer(ExecutionId(uuid4())):
            pass
        async with rollback_conn() as conn:
            workspace_id = f"o6nm-{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="Named project")
            stack = await _build_stack(conn, tmp_path=tmp_path)
            namer = _RecordingNamer()
            try:
                submission = await _capture_submission(
                    conn,
                    artifacts=stack.artifacts,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    brand_id=project.brand_id,
                    label="naming",
                    message_body="Who should we target first?",
                )
                result = await _run_turn(
                    conn,
                    stack,
                    workspace_id=workspace_id,
                    submission=submission,
                    worker_id="o6nm-worker",
                    streaming=True,
                    namer=namer,
                )
                assert result.outcome == AgentExecutionStatus.AWAITING_INPUT.value
                assert len(namer.requests) == 1
                request = namer.requests[0]
                assert request.workspace_id == workspace_id
                assert request.project_id == project.project_id
                assert request.thread_id == submission.thread_id
                assert request.turn_id == submission.turn_id
                assert request.user_message == "Who should we target first?"
                assert request.assistant_message == "I read the brand's knowledge. Shall we start with GI?"
            finally:
                stack.workspaces.close()

    run_async(scenario())
```

The replay guard ("a replayed turn never names again") is by construction rather than by this test: `naming_scope` is passed only from `execute`, never from `replay_committed`, and the engine also checks `not replayed` (Step 7). Do not add a second `_run_turn` on the same submission here — its fleet task is already DONE and the harness would find nothing to claim.

- [ ] **Step 6: Run to verify it fails**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_o6_conversation_composition_db.py -p no:cacheprovider -v -k namer`
Expected: FAIL with `TypeError: build_agent_turn_work_handler() got an unexpected keyword argument 'namer'`.

- [ ] **Step 7: Wire the engine**

`platform/api/clue_api/conversation_turns.py`:

1. Imports: `from clue_api.conversation_naming import ConversationNamer, NamingRequest, TurnNamingLauncher` and `from clue_agents import AgentExecutionStatus` (add to the existing `from clue_agents import (...)` block if not already imported there).
2. `ConversationTurnEngine.__init__`: add keyword `namer: ConversationNamer | None = None` and `self._naming = TurnNamingLauncher(namer=namer)`.
3. In `execute`, the final call becomes:

```python
        return await self._result_from_outcome(
            outcome=outcome,
            turn_id=request.turn_id,
            workspace_id=workspace_id,
            thread_id=request.thread_id,
            stream=stream,
            replayed=committed is not None,
            naming_scope=(request.constitution.project_id, request.user_message_artifact_ref),
        )
```

4. `_result_from_outcome` gains `naming_scope: tuple[str, ArtifactRef] | None = None` (the replay path in `replay_committed` passes nothing). After the assistant message is resolved and its history row appended, before `_project_turn_close`:

```python
        naming_task = None
        if (
            naming_scope is not None
            and not replayed
            and assistant_message
            and outcome.status in (AgentExecutionStatus.COMPLETED, AgentExecutionStatus.AWAITING_INPUT)
        ):
            project_id, user_message_ref = naming_scope
            user_message = (await self.components.artifacts.read(user_message_ref)).decode()
            naming_task = self._naming.start(
                NamingRequest(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    user_message=user_message,
                    assistant_message=assistant_message,
                )
            )
        if stream is not None:
            await self._project_turn_close(
                stream=stream,
                outcome=outcome,
                envelope=envelope,
                assistant_message=assistant_message,
                replayed=replayed,
                naming_task=naming_task,
            )
```

`ArtifactRef` is already imported in that module via `clue_agents` (check the import block; add it if not).

5. `_project_turn_close` gains `naming_task: asyncio.Task[NamingOutcome] | None = None` (import `asyncio` and `NamingOutcome`) and, immediately before `await stream.turn_finished(...)`:

```python
        # §4.1: a fast namer lands before the terminal event (one refetch shows the names); a
        # slow one keeps running detached. The terminal event never waits longer than the grace.
        await self._naming.wait_grace(naming_task)
```

6. `build_conversation_turn_engine(...)` gains `namer: ConversationNamer | None = None` and passes `namer=namer` to the constructor.

`platform/api/clue_api/agent_turn_fleet_wiring.py`: `build_agent_turn_work_handler(...)` gains `namer: ConversationNamer | None = None` (import the protocol) and passes `namer=namer` into its `build_conversation_turn_engine(...)` call. Docstring line: "``namer`` (conversation naming, 2026-09-18) names an untitled chat/project after the first completed turn; ``None`` keeps the placeholders."

`platform/api/clue_api/fleet_main.py`, inside `if settings.chat_enabled and platform_components is not None:` before `agent_turn_handler = build_agent_turn_work_handler(`:

```python
            namer = build_conversation_namer(
                settings=settings,
                secrets=secrets,
                artifacts=platform_components.artifacts,
                conn_factory=transaction,
            )
```

and pass `namer=namer,` into the call. Import `from clue_api.conversation_naming import build_conversation_namer`. `stage0_trial.py`'s builder call is untouched (default `None`).

- [ ] **Step 8: Run the new end-to-end test and the neighbours**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_o6_conversation_composition_db.py tests/api/test_conversation_naming.py -p no:cacheprovider -v`
Expected: all pass (the pre-existing O6 tests included). Then `uv run ruff check platform/api/clue_api/conversation_turns.py platform/api/clue_api/agent_turn_fleet_wiring.py platform/api/clue_api/fleet_main.py platform/api/clue_api/conversation_naming.py` and `uv run mypy platform/api/clue_api/conversation_naming.py platform/api/clue_api/conversation_turns.py` (or the repo's `make typecheck` equivalent limited to these files if mypy is configured per package).

- [ ] **Step 9: Commit**

```bash
git add platform/api/clue_api/conversation_naming.py platform/api/clue_api/conversation_turns.py platform/api/clue_api/agent_turn_fleet_wiring.py platform/api/clue_api/fleet_main.py tests/api/test_conversation_naming.py tests/api/test_o6_conversation_composition_db.py
git commit -m "feat(naming): name the chat and project at the end of the first completed turn

The conversation engine starts the namer once the reply is known, waits NAMING_GRACE_S
before the terminal event and lets a slow call finish detached; the fleet worker composes the
namer from CLUE_CONVERSATION_NAMING_* (spec 2026-09-18-conversation-naming-design §4.1)."
```

---

### Task 7: Home bootstrap births an untitled thread; replay no longer compares titles

**Files:**
- Modify: `platform/api/clue_api/chat/router.py` (`_UNTITLED_PROJECT` ~line 243, `_first_thread_title` ~line 298, `bootstrap_project_route` ~lines 859–920 and ~1012–1030)
- Modify: `platform/api/clue_api/chat/schemas.py` (`ProjectBootstrapThreadWire.title` ~line 580)
- Test: `tests/api/test_home_project_bootstrap_db.py`

**Interfaces:**
- Consumes: Task 1 `UNTITLED_PROJECT_NAME`.
- Produces: `POST /api/v1/projects` response `data.thread.title` is `null`; replay after a rename returns 200.

- [ ] **Step 1: Change the tests first**

In `tests/api/test_home_project_bootstrap_db.py`:
- delete the import of `_first_thread_title` and the test `test_first_thread_title_follows_the_frozen_unicode_rule`;
- in `test_home_bootstrap_is_atomic_and_exact_replay_is_one_project_turn`, replace `assert first["thread"]["title"] == "Start an ABM project for Northstar Labs"` with `assert first["thread"]["title"] is None`;
- add, right after the two `client.post` calls and before the assertions, a rename between the create and a third replay:

```python
            from clue_api.thread_store import set_thread_title
            from clue_spine import set_project_name

            await set_thread_title(
                conn, workspace_id="ws-home-create", thread_id=first["thread"]["id"], title="Renamed by hand"
            )
            await set_project_name(
                conn, workspace_id="ws-home-create", project_id=first["project"]["id"], name="GI outreach"
            )
            async with _client(app) as client:
                after_rename = await client.post("/api/v1/projects", headers=headers, json=request_body)
            assert after_rename.status_code == 200, after_rename.text
            assert after_rename.json()["data"]["thread"]["title"] == "Renamed by hand"
            assert after_rename.json()["data"]["project"]["title"] == "GI outreach"
```

(Place the two imports at the top of the file with the others.) Note: `first` must already be parsed before this block — reorder so `first = created.json()["data"]` runs before the rename.

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_home_project_bootstrap_db.py -p no:cacheprovider -v -k replay`
Expected: FAIL — `first["thread"]["title"]` is the 80-char prefix, and the post-rename replay returns 409.

- [ ] **Step 3: Implement**

`platform/api/clue_api/chat/router.py`:
- replace `_UNTITLED_PROJECT = "Untitled project"` with `from clue_spine import UNTITLED_PROJECT_NAME` (add to the existing `clue_spine` import) and rename every `_UNTITLED_PROJECT` use to `UNTITLED_PROJECT_NAME`;
- delete `_first_thread_title` and the `title = _first_thread_title(body.message)` line; pass `title=None` to `create_thread(...)`;
- change the idempotency check `if thread.project_id != project_id or thread.title != title:` to `if thread.project_id != project_id:` with the comment: `# The title is no longer part of the replay identity: it is born null, generated after the first completed turn, and may have been renamed by hand since (spec 2026-09-18-conversation-naming-design §4.6). The message digest on the submission is what proves the request is the same.`;
- the project-side conflict check keeps `project.name != UNTITLED_PROJECT_NAME` ONLY for the never-replayed create branch? No — it runs on replay too and would 409 after naming. Change it to drop the name comparison: `elif project.workspace_id != who.workspace_id or project.brand_id != body.brand_id or project.status != "active":`;
- in the response, `ProjectBootstrapThreadWire(... title=thread.title ...)` (the stored value: `None` on create, the current title on replay) and `ProjectBootstrapProjectWire(... title=project.name ...)` (already so).

`platform/api/clue_api/chat/schemas.py`: `ProjectBootstrapThreadWire.title: str | None`.

Remove the now-unused `import re` from the router if `_first_thread_title` was its only user (ruff will say).

- [ ] **Step 4: Run the bootstrap tests and the contract tests**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_home_project_bootstrap_db.py tests/api/test_project_read_surfaces_db.py -p no:cacheprovider -v`; `uv run ruff check platform/api/clue_api/chat/router.py platform/api/clue_api/chat/schemas.py`; `grep -rn "_first_thread_title\|_UNTITLED_PROJECT\b" platform tests` must print nothing.
Expected: all pass, ruff clean, grep empty.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/chat/router.py platform/api/clue_api/chat/schemas.py tests/api/test_home_project_bootstrap_db.py
git commit -m "feat(chat): Home births an untitled thread; replay ignores generated or manual names

Retires the R0 80-character first-message title; the thread is born title=null and named
after the first completed turn. The idempotent replay no longer compares thread title or
project name, so a replay after naming or a manual rename returns 200, not 409 (spec §4.6)."
```

---

### Task 8: Frontend — nullable bootstrap thread title

**Files:**
- Modify: `apps/frontend/src/features/projects/model/project-workspace.ts` (`ProjectBootstrapWireSchema.thread.title` ~line 296)
- Modify: `apps/frontend/src/features/projects/data/project-home.repository.ts` (fixture `create`, ~line 86)
- Test: `apps/frontend/src/features/projects/data/project-home.repository.test.ts`

**Interfaces:**
- Produces: `ProjectBootstrap.thread.title: string | null`.

- [ ] **Step 1: Change the tests first**

In `project-home.repository.test.ts`: the HTTP test's stubbed response (~line 25) becomes `title: null`, and its assertion (~line 76) becomes `assert.equal(created.thread.title, null);`. In the fixture test, assert `created.thread.title === null` as well (add the line where the fixture result is checked).

- [ ] **Step 2: Run to verify it fails**

Run (from `apps/frontend`): `npx tsx --test src/features/projects/data/project-home.repository.test.ts`
Expected: FAIL — Zod refuses `null` for `thread.title`.

- [ ] **Step 3: Implement**

`project-workspace.ts`: in `ProjectBootstrapWireSchema`, `thread.title: z.string().min(1).nullable()`. The transform already copies `data.thread.title` through.

`project-home.repository.ts` fixture: `title: null,` in place of `title: message.trim(),` with the comment `// Born untitled; the conversation namer titles it after the first completed turn.`

Search for any consumer that assumed a string: `grep -rn "thread.title" apps/frontend/src/features/projects/hooks/use-project-home*.ts apps/frontend/src/app` — the Home flow only navigates to `href`, so nothing else should need a change; if `tsc` complains, use `thread.title ?? UNTITLED_THREAD_LABEL` from `../model/chat-thread` at that site.

- [ ] **Step 4: Verify**

Run (from `apps/frontend`): `npx tsx --test src/features/projects/data/project-home.repository.test.ts`, `npx tsc --noEmit -p .` (only the three known pre-existing errors), `npm run lint`.
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/projects/model/project-workspace.ts apps/frontend/src/features/projects/data/project-home.repository.ts apps/frontend/src/features/projects/data/project-home.repository.test.ts
git commit -m "feat(frontend): Home bootstrap thread title is nullable

The Home-created thread is born untitled and shows the New chat label until the conversation
namer titles it (spec 2026-09-18-conversation-naming-design §4.7)."
```

---

### Task 9: Frontend — bounded catch-up poll while a placeholder is visible

**Files:**
- Create: `apps/frontend/src/features/projects/hooks/use-naming-catch-up.ts`
- Test: `apps/frontend/src/features/projects/hooks/use-naming-catch-up.test.ts`
- Modify: `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts` (props ~line 267; the terminal-event branch ~line 838; `loadThreads` ~line 478)
- Modify: `apps/frontend/src/features/projects/components/project-workspace-shell.tsx` (~line 86)

**Interfaces:**
- Produces: `NAMING_CATCH_UP_INTERVAL_MS = 5_000`, `NAMING_CATCH_UP_MAX_TICKS = 12`, `namingCatchUpSchedule({ namingPending, terminalRevision }): { intervalMs, maxTicks } | null` (pure), `useNamingCatchUp({ namingPending, terminalRevision, tick }): void` (effect), controller prop `projectTitle: string`, controller field `terminalTurnRevision: number`.

The controller already calls `invalidateProjectCatalog()` on every terminal turn event (that is the one refetch of the spec). What it lacks is (a) reloading its OWN thread list on that refetch, so the chat header's `threadLabelFor(activeThread)` picks up the generated title, and (b) the bounded poll for a name that landed after the grace.

- [ ] **Step 1: Write the failing test for the pure planner and the hook**

```ts
// apps/frontend/src/features/projects/hooks/use-naming-catch-up.test.ts
import assert from "node:assert/strict";
import test from "node:test";
import {
  NAMING_CATCH_UP_INTERVAL_MS,
  NAMING_CATCH_UP_MAX_TICKS,
  namingCatchUpSchedule,
} from "./use-naming-catch-up";

test("constants match the spec: every 5 s, at most 12 times", () => {
  assert.equal(NAMING_CATCH_UP_INTERVAL_MS, 5_000);
  assert.equal(NAMING_CATCH_UP_MAX_TICKS, 12);
});

test("no terminal event yet → nothing to schedule", () => {
  assert.equal(namingCatchUpSchedule({ namingPending: true, terminalRevision: 0 }), null);
});

test("a terminal event while a placeholder is visible schedules the bounded poll", () => {
  assert.deepEqual(namingCatchUpSchedule({ namingPending: true, terminalRevision: 1 }), {
    intervalMs: 5_000,
    maxTicks: 12,
  });
});

test("nothing pending → nothing scheduled, even after a terminal event", () => {
  assert.equal(namingCatchUpSchedule({ namingPending: false, terminalRevision: 3 }), null);
});
```

- [ ] **Step 2: Run to verify it fails**

Run (from `apps/frontend`): `npx tsx --test src/features/projects/hooks/use-naming-catch-up.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the hook**

```ts
// apps/frontend/src/features/projects/hooks/use-naming-catch-up.ts
"use client";

import { useEffect, useRef } from "react";

/**
 * Conversation naming, frontend half (spec 2026-09-18-conversation-naming-design §4.7).
 *
 * The backend names an untitled chat (and an untitled project) after the first completed
 * turn, usually before the terminal turn event — and the controller's existing invalidate on
 * that event shows the names. A naming call slower than the engine's grace lands AFTER the
 * event, so while a placeholder is still visible we refetch a bounded number of times and
 * stop the moment both names are present. Only first turns ever poll.
 */
export const NAMING_CATCH_UP_INTERVAL_MS = 5_000;
export const NAMING_CATCH_UP_MAX_TICKS = 12;

export interface NamingCatchUpSchedule {
  intervalMs: number;
  maxTicks: number;
}

/** Pure: what to schedule for this (pending, terminal-revision) pair, or nothing. */
export function namingCatchUpSchedule({
  namingPending,
  terminalRevision,
}: {
  namingPending: boolean;
  terminalRevision: number;
}): NamingCatchUpSchedule | null {
  if (terminalRevision === 0 || !namingPending) return null;
  return { intervalMs: NAMING_CATCH_UP_INTERVAL_MS, maxTicks: NAMING_CATCH_UP_MAX_TICKS };
}

export function useNamingCatchUp({
  namingPending,
  terminalRevision,
  tick,
}: {
  /** True while the active chat has no title or the project is still "Untitled project". */
  namingPending: boolean;
  /** Increments on every terminal turn event of the active thread. */
  terminalRevision: number;
  /** One refetch: invalidate the catalog and reload the thread list. */
  tick: () => void;
}): void {
  const tickRef = useRef(tick);
  tickRef.current = tick;
  useEffect(() => {
    const schedule = namingCatchUpSchedule({ namingPending, terminalRevision });
    if (schedule === null) return;
    let ticks = 0;
    const handle = setInterval(() => {
      ticks += 1;
      tickRef.current();
      if (ticks >= schedule.maxTicks) clearInterval(handle);
    }, schedule.intervalMs);
    return () => clearInterval(handle);
    // `namingPending` flipping to false clears the interval through the cleanup above.
  }, [namingPending, terminalRevision]);
}
```

- [ ] **Step 4: Wire the controller and the shell**

`use-project-chat-controller.ts`:
1. Props: add `projectTitle: string` to the `useProjectChatController({ projectId, initialThreadId, projectTitle })` parameter type and destructure it.
2. State: `const [terminalTurnRevision, setTerminalTurnRevision] = useState(0);`.
3. In the stream handler, the existing block

```ts
            if (isTerminalTurnState(streamedState)) {
              invalidateProjectCatalog();
            }
```
becomes
```ts
            if (isTerminalTurnState(streamedState)) {
              invalidateProjectCatalog();
              // Conversation naming (§4.7): the header reads the thread's title from THIS
              // controller's list, so reload it alongside the catalog, and let the bounded
              // catch-up poll know a turn just ended. `attach` is only ever called for the
              // thread this controller is showing, so every frame here is the active thread's.
              void loadThreads().catch(() => undefined);
              setTerminalTurnRevision((current) => current + 1);
            }
```
4. After `activeThread` is derived (~line 1276), add:

```ts
  const namingPending =
    (activeThread !== null && activeThread.title === null) ||
    projectTitle === "Untitled project";
  useNamingCatchUp({
    namingPending,
    terminalRevision: terminalTurnRevision,
    tick: () => {
      invalidateProjectCatalog();
      void loadThreads().catch(() => undefined);
    },
  });
```
and import `useNamingCatchUp` from `./use-naming-catch-up`. Expose `terminalTurnRevision` on the returned `ProjectChatController` (add `terminalTurnRevision: number;` to the interface) so tests can observe it.

`project-workspace-shell.tsx` (~line 86): `useProjectChatController({ projectId: workspace.id, initialThreadId: initial.threadId, projectTitle: workspace.title })`. `workspace.title` refreshes because `use-project-workspace-loader` refetches on the catalog revision, so `namingPending` flips false once the project is named.

Fix every other caller of `useProjectChatController` (the lock test constructs it with `{ projectId, initialThreadId }` — add `projectTitle: "Named project"` there).

- [ ] **Step 5: Verify**

Run (from `apps/frontend`): `npx tsx --test src/features/projects/hooks/use-naming-catch-up.test.ts src/features/projects/hooks/use-project-chat-controller-lock.test.ts`, `npx tsc --noEmit -p .`, `npm run lint`.
Expected: pass (the lock test still passes with the new prop).

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/features/projects/hooks/use-naming-catch-up.ts apps/frontend/src/features/projects/hooks/use-naming-catch-up.test.ts apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts apps/frontend/src/features/projects/hooks/use-project-chat-controller-lock.test.ts apps/frontend/src/features/projects/components/project-workspace-shell.tsx
git commit -m "feat(frontend): reload the thread list on terminal turns and poll briefly for late names

The chat header picks up a generated title on the same refetch the sidebar already does; while
a placeholder is still visible after a terminal turn, the shell refetches every 5 s for at most
a minute (spec 2026-09-18-conversation-naming-design §4.7)."
```

---

### Task 10: Contract, memory and spec status

**Files:**
- Modify: `apps/frontend/docs/api-contracts/projects.md` (§4, ~lines 1074–1090; the `"title": "Untitled project"` example in §5 keeps its value but gains one sentence)
- Modify: `docs/superpowers/specs/archive/2026-09-18-conversation-naming-design.md` (status line)
- Modify: `_memory/2026-09-18-conversation-naming-design.md` and `_memory/README.md`

- [ ] **Step 1: Rewrite contract §4**

Replace the whole "### 4. Deterministic first-thread title" section with:

```markdown
### 4. Generated names (since 2026-09-18)

The Home-created thread is born with `title: null`; the project is born as
`"Untitled project"`. Both are placeholders. After the thread's first
**completed** turn (status `completed` or `awaiting_input`, with a non-empty
reply) the server makes one auxiliary model call and writes:

- the thread's `title` — 2 to 5 words naming the task of the chat — only if
  the title is still `null`;
- the project's `title` — 2 to 5 words naming the marketing motion — only if
  it is still `"Untitled project"`.

A manual rename (`PATCH …/threads/:id` or `PATCH /projects/:id`) is never
overwritten: the generated write is conditional on the placeholder. A failed
or slow naming call leaves the placeholder; the next completed turn tries
again. The frontend shows `New chat` / `Untitled project` until a name lands
and refetches the sidebar and project shell on the terminal turn event (and,
while a placeholder is still visible, every 5 s for at most 60 s).

Replaying `POST /projects` with the same key after naming or a manual rename
returns `200` with the current names; the title is not part of the replay
identity.

Historical note: until 2026-09-18 the first thread's title was the message's
first 80 code points (the "R0" rule). Retired.
```

Under §5, after the JSON example, add: `\`title\` reads \`"Untitled project"\` until the first completed turn names the project (§4).`

- [ ] **Step 2: Update the spec status and the memory note**

Spec status line → `**Status:** approved 2026-09-18; implemented on branch research-streaming-v3 per docs/superpowers/plans/2026-09-18-conversation-naming.md.` In `_memory/2026-09-18-conversation-naming-design.md` append a "## Implementation" section listing the commits (short SHAs) of Tasks 1–10, the verification commands run and their results, and the owed live acceptance (spec §6 items 1–8 on the lane stack with a real key — founder-triggered). Update the README line for that note accordingly.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/docs/api-contracts/projects.md docs/superpowers/specs/archive/2026-09-18-conversation-naming-design.md _memory/2026-09-18-conversation-naming-design.md _memory/README.md
git commit -m "docs: conversation naming — contract §4 rewritten, spec status, session record"
```

---

## Verification at hand-off (owed by the executor, recorded in `_memory`)

1. Backend focused suites green: `tests/clue_spine/test_project_naming_db.py`, `tests/api/test_thread_naming_store_db.py`, `tests/api/test_conversation_naming.py`, `tests/api/test_conversation_naming_db.py`, `tests/api/test_o6_conversation_composition_db.py`, `tests/api/test_home_project_bootstrap_db.py`, `tests/api/test_project_read_surfaces_db.py`, plus `tests/api/test_agent_registry_wiring.py` and `tests/agents/test_tool_authority_audit.py` (the namer must not have changed any tool grant).
2. `uv run ruff check platform libs tests` on the touched files; `make typecheck` if it runs in under ten minutes, otherwise mypy on the touched modules.
3. Frontend: `npm test`, `npm run lint`, `npx tsc --noEmit -p .`; `npm run build` with the lane dev server stopped.
4. Live acceptance (spec §6, founder-triggered, spends money): start the lane stack via `./scripts/dev_stack_trenton.sh up` with a real `CLUE_OPENROUTER_API_KEY`, send a first message from Home, watch the sidebar and header rename after the reply; rename a chat by hand mid-turn and confirm it survives; set `CLUE_CONVERSATION_NAMING_ENABLED=false`, restart the workers, confirm placeholders stay and no `provider_call_ledger` row with `label = 'conversation_naming'` appears; check `GET /cost/report` shows the naming rows.
