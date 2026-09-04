# Page First & First-Batch Canvas — Implementation Plan (Editor Quality Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fresh (pageless) ad document gets its page in the agent's FIRST write, the asset tools refuse to spend on a pageless scene, and the editor canvas shows the artboard on the first streamed operation batch instead of after the first checkpoint reload.

**Architecture:** Two independent halves. (1) Agent runtime (Python, `subsystems/clue-design/apps/agent_runtime`): one pre-spend guard on `LumenDesignTools` used by `generate_image`, `generate_qr` and `fetch_logo` (refuse with a typed payload BEFORE the provider/vendor call), plus a page-first rule in the three prompt sections that drive a design turn and in the LinkedIn ad skill. (2) Frontend (TypeScript, `apps/frontend`): the canvas derives its effective page id from the scene it is DRAWING (loaded id when present, else the first page of the streamed scene) in one pure helper, and the pageless notice keys off the same value.

**Tech Stack:** Python 3.12 + pytest (agent runtime; `FakeCoreClient` fixture, monkeypatched providers); TypeScript + node:test via `npm test` (frontend, `*.test.ts` glob); no new dependencies.

**Spec:** `docs/superpowers/plans/2026-09-04-editor-quality-roadmap.md` — Plan 2, items C and D. Root causes verified there; this plan does not re-derive them.

## Global Constraints

- Python tests run from `subsystems/clue-design`: `set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/<file> -q`. None of this plan's Python tests touch the database.
- Frontend gate from `apps/frontend`: `npm run design-system:build && npm run lint && npm run build`; unit tests: `npx tsx --test <file>` for one file, `npm test` for all.
- Error code (exact): `scene.page_required`. Trace event names (exact): `generate_image_refused_pageless`, `generate_qr_refused_pageless`, `fetch_logo_refused_pageless`.
- Refusal message (exact): `<tool> refused: the scene has no page/artboard yet, so nothing can be registered in it.` Hint (exact): `Author the page first — compile_dsl_block with a \`page <id> size(...)\` line, the whole design in one block — then call <tool> again.` (`<tool>` is the tool's name: `generate_image` / `generate_qr` / `fetch_logo`).
- The web lane (`LumenWebTools`, `prompts_web.py`) is out of scope: web documents are not page-authored the same way.
- Only the words below are added to prompts/skill; no other prompt text moves (prompt edits are diffs a reviewer must be able to read).
- Frontend: no new UI, no copy changes — `PAGELESS_SCENE_NOTICE` stays verbatim. The editing session (inspector, layer tree) keeps receiving the LOADED scene and LOADED page id; only the canvas's own drawing/hit-testing/notice use the effective id.
- Commit locally per task with the message given; never push; no AI attribution trailers; never `git stash`.

---

### Task 1: Pre-spend page guard on the three asset tools

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py` — add `PAGE_REQUIRED_CODE` + `_refuse_without_page`, call it at the top of `generate_image` (~line 966), `generate_qr` (~line 854) and `fetch_logo` (~line 1347).
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_page_first_guard.py` (new)

**Interfaces:**
- Consumes: `LumenDesignTools(config, prompt, initial_scene=None)`; `self.scene` (a scene dict; `FakeCoreClient.new_scene` returns `pages: {}`); `self.record(role, event, input_summary=..., output_summary=..., payload=...)`; module-level `image_provider` (tests stub it as `lumen_agent.tools.substrate.image_provider`); `logo_fetch.fetch_logo_family` (tests stub `lumen_agent.tools.logo_fetch.fetch_logo_family`); `self.core.generate_qr` (tests stub via `monkeypatch.setattr(tools.core, "generate_qr", ...)`).
- Produces: `PAGE_REQUIRED_CODE = "scene.page_required"`; `LumenDesignTools._refuse_without_page(self, tool: str) -> Optional[str]` (JSON string payload when refused, `None` when a page exists). Task 2's prompt text names the code.

- [ ] **Step 1: Write the failing tests**

```python
"""Editor Quality Plan 2, item C: the asset tools refuse on a pageless scene BEFORE spending.

Run `run_0452aae9…` fetched a logo and generated a hero image before any page existed; every
registration was refused by the engine (LUMV0100) AFTER the vendor/model had been paid. The
guard moves that refusal in front of the spend: a pageless scene costs one tool call, never an
image generation or a vendor request.
"""

from __future__ import annotations

import json
import types

import pytest

from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent.tools import logo_fetch
from lumen_agent.tools.substrate import PAGE_REQUIRED_CODE, LumenDesignTools


@pytest.fixture()
def tools(tmp_path, monkeypatch) -> LumenDesignTools:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    return LumenDesignTools(runtime_config(tmp_path), "Make a LinkedIn ad")


def _give_page(tools: LumenDesignTools) -> None:
    """FakeCoreClient.compile_dsl_into_scene plants `page_test`; any source will do."""
    tools.compile_dsl_block("page page_test size(1080,1080,px)")
    assert tools.scene["pages"], "fixture must have planted a page"


def _install_counting_image_model(monkeypatch) -> dict:
    calls = {"n": 0}

    def fake_generate(**kwargs):
        calls["n"] += 1
        return types.SimpleNamespace(
            image_bytes=b"\x89PNG-generated-bytes",
            mime_type="image/png",
            model="test/image-model",
            provenance={"created_by": "agent", "source_label": "image generation", "notes": []},
        )

    stub = types.SimpleNamespace(
        is_configured=lambda: True,
        configured_model_id=lambda: "test/image-model",
        generate=fake_generate,
    )
    monkeypatch.setattr("lumen_agent.tools.substrate.image_provider", stub)
    return calls


def test_generate_image_refuses_on_a_pageless_scene_without_calling_the_model(tools, monkeypatch):
    calls = _install_counting_image_model(monkeypatch)
    assert tools.scene["pages"] == {}

    result = json.loads(tools.generate_image("a calm clinic reception"))

    assert result["status"] == "error"
    assert result["error_code"] == PAGE_REQUIRED_CODE == "scene.page_required"
    assert result["message"] == (
        "generate_image refused: the scene has no page/artboard yet, so nothing can be "
        "registered in it."
    )
    assert result["hint"] == (
        "Author the page first — compile_dsl_block with a `page <id> size(...)` line, the "
        "whole design in one block — then call generate_image again."
    )
    assert calls["n"] == 0, "the model must not be paid for a pageless scene"


def test_generate_image_calls_the_model_once_when_a_page_exists(tools, monkeypatch):
    calls = _install_counting_image_model(monkeypatch)
    _give_page(tools)

    result = json.loads(tools.generate_image("a calm clinic reception"))

    assert result["image"]["status"] == "ok"
    assert calls["n"] == 1


def test_generate_qr_refuses_on_a_pageless_scene_without_calling_the_core(tools, monkeypatch):
    calls = {"n": 0}

    def fake_generate_qr(**kwargs):
        calls["n"] += 1
        raise AssertionError("must not be reached on a pageless scene")

    monkeypatch.setattr(tools.core, "generate_qr", fake_generate_qr, raising=False)

    result = json.loads(tools.generate_qr("https://example.com"))

    assert result["status"] == "error"
    assert result["error_code"] == "scene.page_required"
    assert result["message"].startswith("generate_qr refused:")
    assert result["hint"].endswith("then call generate_qr again.")
    assert calls["n"] == 0


def test_fetch_logo_refuses_on_a_pageless_scene_without_calling_the_vendor(tools, monkeypatch):
    calls = {"n": 0}

    def fake_family(requested, **kwargs):
        calls["n"] += 1
        raise AssertionError("must not be reached on a pageless scene")

    monkeypatch.setattr(logo_fetch, "fetch_logo_family", fake_family)

    result = json.loads(tools.fetch_logo("ramp.com", "Ramp"))

    assert result["status"] == "error"
    assert result["error_code"] == "scene.page_required"
    assert result["message"].startswith("fetch_logo refused:")
    assert result["hint"].endswith("then call fetch_logo again.")
    assert calls["n"] == 0


def test_the_refusal_is_recorded_in_the_trace(tools, monkeypatch):
    _install_counting_image_model(monkeypatch)
    recorded: list[tuple] = []
    original = tools.record

    def spy(role, event, **kwargs):
        recorded.append((role, event, kwargs))
        return original(role, event, **kwargs)

    monkeypatch.setattr(tools, "record", spy)

    tools.generate_image("a hero")

    events = [event for _, event, _ in recorded]
    assert "generate_image_refused_pageless" in events
    payload = next(k for _, e, k in recorded if e == "generate_image_refused_pageless")["payload"]
    assert payload["error_code"] == "scene.page_required"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `subsystems/clue-design`): `set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/test_page_first_guard.py -q`
Expected: collection error `ImportError: cannot import name 'PAGE_REQUIRED_CODE'`.

If `tools.compile_dsl_block` is not the compile tool's name on `LumenDesignTools`, find the method that calls `self.core.compile_dsl_into_scene` and use it in `_give_page` — record the name in the report. If `FakeCoreClient` has no `generate_qr`, the `raising=False` monkeypatch still installs one; that is intended.

- [ ] **Step 3: Implement the guard**

In `substrate.py`, near the other module constants (after the `image_cache` import block, ~line 30), add:

```python
#: Editor Quality Plan 2 (item C): the asset tools refuse on a pageless scene BEFORE they spend.
#: Registering an asset needs a page (engine rule LUMV0100); paying a model or a vendor first
#: and discovering that afterwards cost `run_0452aae9…` ~10 minutes and its repair round.
PAGE_REQUIRED_CODE = "scene.page_required"
```

On `LumenDesignTools`, next to `_tool_error` (~line 2354), add:

```python
    def _refuse_without_page(self, tool: str) -> Optional[str]:
        """The pre-spend page guard: a JSON refusal when the scene has no page, else None.

        Checked at the TOP of generate_image / generate_qr / fetch_logo, before any provider,
        core or vendor call. The engine would refuse the registration anyway (LUMV0100); this
        moves that answer in front of the spend, so a misordered author loses one tool call
        and nothing else. The hint names the fix in the author's own vocabulary.
        """
        if self.scene.get("pages"):
            return None
        payload: JsonObject = {
            "status": "error",
            "error_code": PAGE_REQUIRED_CODE,
            "message": (
                f"{tool} refused: the scene has no page/artboard yet, so nothing can be "
                "registered in it."
            ),
            "hint": (
                "Author the page first — compile_dsl_block with a `page <id> size(...)` line, "
                f"the whole design in one block — then call {tool} again."
            ),
        }
        self.record(
            "coordinator",
            f"{tool}_refused_pageless",
            output_summary=payload["message"],
            payload=payload,
        )
        return json.dumps(payload, indent=2)
```

Then, as the FIRST statement of each tool body (after the docstring):

```python
        # generate_image (before `asset_id = ...`):
        refused = self._refuse_without_page("generate_image")
        if refused is not None:
            return refused
```
```python
        # generate_qr (before `asset_id = ...`):
        refused = self._refuse_without_page("generate_qr")
        if refused is not None:
            return refused
```
```python
        # fetch_logo (before `requested = (domain or "").strip()`):
        refused = self._refuse_without_page("fetch_logo")
        if refused is not None:
            return refused
```

Also update the three docstrings' one sentence about the page: in `generate_image` replace "The scene must already contain a page/artboard (author the layout first) or registration fails with a retryable error." with "The scene must already contain a page/artboard: on a pageless scene this tool REFUSES before generating (error `scene.page_required`) — author the page first."; add the same sentence (with the tool's name) to `generate_qr`'s and `fetch_logo`'s docstrings, one line each. Keep the existing post-registration `hint` blocks (they still cover a registration that fails for another reason).

- [ ] **Step 4: Run the new tests and the neighbours**

Run: `... pytest apps/agent_runtime/tests/test_page_first_guard.py apps/agent_runtime/tests/test_fetch_logo_tool.py apps/agent_runtime/tests/test_deepagent_harness.py -q`
Expected: the 5 new tests pass; `test_fetch_logo_tool.py` and `test_deepagent_harness.py` unchanged from before your change (run them once BEFORE editing to record the baseline counts; several harness tests build a scene with a page via the fixture's compile, so they must still pass). If any pre-existing test now hits the guard, it was calling an asset tool on a pageless scene — give it a page with the same `compile_dsl_block` line and record which test.

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py subsystems/clue-design/apps/agent_runtime/tests/test_page_first_guard.py
git commit -m "feat(design-agent): asset tools refuse on a pageless scene before spending (scene.page_required)"
```

---

### Task 2: Page-first rule in the prompts and the LinkedIn ad skill

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts.py` — `_ORCHESTRATOR_TEMPLATE` step 3 (imagery bullet, ~line 143), `_AUTHOR_HEADER` page bullet (~line 335), `_AUTHOR_FAST_LOOP_WORK_LOOP` step 2 (~line 576).
- Modify: `subsystems/clue-design/apps/agent_runtime/knowledge_docs/skills/linkedin-square-ad/SKILL.md` — the "Surface" bullet (~line 33).
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_prompts_page_first.py` (new)

**Interfaces:**
- Consumes: `PAGE_REQUIRED_CODE == "scene.page_required"` (Task 1).
- Produces: nothing programmatic; the exact sentences below.

- [ ] **Step 1: Write the failing test**

```python
"""Editor Quality Plan 2, item C: the page-first rule reaches every role that can spend."""

from __future__ import annotations

import inspect
from pathlib import Path

from lumen_agent import prompts

SKILL = (
    Path(prompts.__file__).resolve().parents[1]
    / "knowledge_docs" / "skills" / "linkedin-square-ad" / "SKILL.md"
)

DIRECTOR_RULE = (
    "PAGE BEFORE ASSETS: on a document with no page yet (artboard_id is null and the scene "
    "digest shows zero pages), delegate the author's whole-design compile FIRST and only "
    "then fetch logos or generate imagery — generate_image, generate_qr and fetch_logo refuse "
    "on a pageless scene (`scene.page_required`) without spending, so calling them first only "
    "wastes a tool call."
)
AUTHOR_RULE = (
    "PAGE FIRST. On a document with no page, the `page …` line is the FIRST line of your "
    "first compile, and that compile is the whole design. Nothing can be registered in a "
    "pageless scene: generate_image, generate_qr and fetch_logo refuse before spending "
    "(`scene.page_required`) until a page exists — never call an asset tool on a pageless "
    "scene."
)
WORK_LOOP_RULE = (
    "On a pageless document the page line leads that block; imagery, logos and QR codes "
    "come AFTER the page exists — the asset tools refuse on a pageless scene without "
    "spending."
)
SKILL_RULE = (
    "Author it in your FIRST compile, before any imagery or logo — a pageless scene "
    "registers nothing."
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_director_template_orders_the_page_before_assets():
    assert _flat(DIRECTOR_RULE) in _flat(prompts._ORCHESTRATOR_TEMPLATE)


def test_the_author_header_puts_the_page_line_first():
    assert _flat(AUTHOR_RULE) in _flat(prompts._AUTHOR_HEADER)


def test_the_fast_loop_work_loop_orders_assets_after_the_page():
    assert _flat(WORK_LOOP_RULE) in _flat(prompts._AUTHOR_FAST_LOOP_WORK_LOOP)


def test_every_rule_names_the_guard_code_the_tools_actually_return():
    from lumen_agent.tools.substrate import PAGE_REQUIRED_CODE

    source = inspect.getsource(prompts)
    assert source.count(PAGE_REQUIRED_CODE) >= 2  # director + author header


def test_the_linkedin_ad_skill_orders_the_page_first():
    assert _flat(SKILL_RULE) in _flat(SKILL.read_text())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `... pytest apps/agent_runtime/tests/test_prompts_page_first.py -q`
Expected: 5 failures (assertion errors; the sentences are not present yet).

- [ ] **Step 3: Add the four sentences, verbatim, wrapped to the file's line width**

`_ORCHESTRATOR_TEMPLATE`, step 3, immediately after the `imagery:` bullet's last line ("...view() candidates BEFORE deciding, every create turn).") and BEFORE "These are your declared intentions":

```
   PAGE BEFORE ASSETS: on a document with no page yet (artboard_id is null and
   the scene digest shows zero pages), delegate the author's whole-design
   compile FIRST and only then fetch logos or generate imagery —
   generate_image, generate_qr and fetch_logo refuse on a pageless scene
   (`scene.page_required`) without spending, so calling them first only wastes
   a tool call.
```

`_AUTHOR_HEADER`, a new bullet right after "- YOU author every page. ... from the direction you were given.":

```
- PAGE FIRST. On a document with no page, the `page …` line is the FIRST line
  of your first compile, and that compile is the whole design. Nothing can be
  registered in a pageless scene: generate_image, generate_qr and fetch_logo
  refuse before spending (`scene.page_required`) until a page exists — never
  call an asset tool on a pageless scene.
```

`_AUTHOR_FAST_LOOP_WORK_LOOP`, step 2, right after "That is two compiles and two extra minutes for one design.":

```
   On a pageless document the page line leads that block; imagery, logos and
   QR codes come AFTER the page exists — the asset tools refuse on a pageless
   scene without spending.
```

`SKILL.md`, the "Surface" bullet, appended after "The content column between the default margins is 888pt wide.":

```
  Author it in your FIRST compile, before any imagery or logo — a pageless
  scene registers nothing.
```

The test flattens whitespace, so wrap freely at the file's width; do not change any other word.

- [ ] **Step 4: Run the tests**

Run: `... pytest apps/agent_runtime/tests/test_prompts_page_first.py apps/agent_runtime/tests/test_prompts_logo_cells.py apps/agent_runtime/tests/test_generative_imagery_skill.py -q`
Expected: all pass (the skill-corpus tests in `test_generative_imagery_skill.py` check cited paths/identifiers; the new sentences cite only real tool names).

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts.py subsystems/clue-design/apps/agent_runtime/knowledge_docs/skills/linkedin-square-ad/SKILL.md subsystems/clue-design/apps/agent_runtime/tests/test_prompts_page_first.py
git commit -m "feat(design-agent): page-first rule for the director, the author and the LinkedIn ad skill"
```

---

### Task 3: The canvas derives its page from the scene it draws

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-pageless.ts` — add `effectiveScenePageId`.
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-pageless.test.ts` — new cases.
- Modify: `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx` — destructure at ~line 616, `drawnScene`/`pagelessNotice` at ~lines 690–701, the three `onSceneChange` calls (~873, ~892, ~1515).

**Interfaces:**
- Consumes: `firstPageId(scene)` from `../engine/scene/sceneQueries`; `Scene`, `PageId` from `../engine/scene/contracts`.
- Produces: `export function effectiveScenePageId(loadedPageId: PageId | null, drawnScene: Scene | null): PageId | null`.

- [ ] **Step 1: Write the failing tests** (append to `scene-pageless.test.ts`; add `effectiveScenePageId` to the import)

```ts
it("Plan 2 item D: a pageless load takes its page from the scene being drawn", () => {
  // The document loaded with `pages: {}` (pageId null). The reveal pump then
  // applied a streamed `add_page`, so the DRAWN scene has a page. The canvas
  // must draw that page now, not after the next checkpoint reload.
  assert.equal(effectiveScenePageId(null, HARVESTED_AD_PAGE), AD_PAGE_ID);
});

it("a loaded page id wins over the drawn scene", () => {
  assert.equal(effectiveScenePageId(AD_PAGE_ID, PAGELESS_SCENE), AD_PAGE_ID);
  assert.equal(effectiveScenePageId(AD_PAGE_ID, HARVESTED_AD_PAGE), AD_PAGE_ID);
});

it("nothing drawn and nothing loaded is still no page", () => {
  assert.equal(effectiveScenePageId(null, null), null);
  assert.equal(effectiveScenePageId(null, PAGELESS_SCENE), null);
});

it("the pageless notice clears the moment the drawn scene has a page", () => {
  const drawn = HARVESTED_AD_PAGE;
  const pageId = effectiveScenePageId(null, drawn);
  assert.equal(scenePagelessNotice(drawn, pageId), null);
  // …and still shows while the drawn scene is pageless.
  assert.equal(
    scenePagelessNotice(PAGELESS_SCENE, effectiveScenePageId(null, PAGELESS_SCENE)),
    PAGELESS_SCENE_NOTICE,
  );
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `apps/frontend`): `npx tsx --test src/features/design-editor/adapter/scene-pageless.test.ts`
Expected: fails to compile/import (`effectiveScenePageId` is not exported).

- [ ] **Step 3: Implement the helper**

In `scene-pageless.ts`, add the import `import { firstPageId } from "../engine/scene/sceneQueries";` and:

```ts
/**
 * Editor Quality Plan 2, item D — the page the canvas should DRAW.
 *
 * `use-scene-document` picks `pageId = firstPageId(loaded.scene)` ONCE at
 * load. A chat-born ad loads pageless (`open_design_leg@4` births `pages: {}`),
 * so that id stays null even after the reveal pump has applied a streamed
 * `add_page` — the engine has the page, the drawn scene has the page, and the
 * stage kept showing the pageless notice until a checkpoint reload replaced
 * the loaded scene. This is the one derivation both the artboard model and
 * the notice read: the loaded id when there is one, else the first page of
 * whatever scene is being drawn.
 */
export function effectiveScenePageId(
  loadedPageId: PageId | null,
  drawnScene: Scene | null,
): PageId | null {
  if (loadedPageId !== null) {
    return loadedPageId;
  }
  return drawnScene ? firstPageId(drawnScene) : null;
}
```

- [ ] **Step 4: Run the helper tests**

Run: `npx tsx --test src/features/design-editor/adapter/scene-pageless.test.ts`
Expected: all pass (5 existing + 4 new).

- [ ] **Step 5: Wire the canvas**

In `scene-artifact-canvas.tsx`:

1. Import: `import { effectiveScenePageId, scenePagelessNotice } from "../adapter/scene-pageless";`
2. At the `useSceneDocument` destructure (~line 616) rename `pageId,` to `pageId: loadedPageId,`.
3. Directly after that destructure (before any use of `pageId`), add — and DELETE the later `const drawnScene = displayScene ?? scene;` at ~line 701 (keep its comment block above the new location):

```ts
  // Plan 2 item D: the scene being DRAWN (Task 9's `displayScene` while the
  // reveal pump streams, else the loaded scene) and the page derived from it.
  // A pageless load gets its page from the first streamed `add_page`, not
  // from the next checkpoint reload. `loadedPageId` is still what the editing
  // session receives (below): the inspector and layer tree read the LOADED
  // scene, and a page id that scene does not contain would be a lie to them.
  const drawnScene = displayScene ?? scene;
  const pageId = effectiveScenePageId(loadedPageId, drawnScene);
```

4. `const pagelessNotice = scenePagelessNotice(scene, pageId);` → `scenePagelessNotice(drawnScene, pageId)`.
5. The three `onSceneChangeRef.current?.(…, pageId, documentId)` calls (~873, ~892, ~1515) pass `loadedPageId` instead of `pageId`, and the `useEffect` dependency list at ~1516 lists `loadedPageId` in place of `pageId`.
6. Everything else that reads `pageId` (artboard model, hit-test, gestures, viewport key, selection) keeps reading the effective id unchanged.

Run the type-check: `npx tsc --noEmit -p tsconfig.json` (or `npm run build` if the project has no standalone tsc script). Expected: clean.

- [ ] **Step 6: Run the design-editor suite and the gate**

Run: `npx tsx --test "src/features/design-editor/**/*.test.ts"` then `npm run design-system:build && npm run lint && npm run build`.
Expected: all pass; lint has only the 2 pre-existing warnings.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/features/design-editor/adapter/scene-pageless.ts apps/frontend/src/features/design-editor/adapter/scene-pageless.test.ts apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx
git commit -m "fix(design-editor): canvas draws the first streamed page on a pageless load instead of waiting for a checkpoint reload"
```

---

### Task 4: Live proof on colombo and records (controller)

Not delegated. Steps:

1. Restart colombo's fleet worker and design API (Python changed; frontend hot-reloads). Confirm no run is in flight first.
2. In the Apollo project, open a NEW chat and send: "Make a LinkedIn square ad for Apollo aimed at sales leaders at Ramp: headline about pipeline that shows up on time, one proof stat, Read the story CTA. Use the Ramp logo." Watch the thread route's artifact panel.
3. Proof of item D: the artboard appears on the first `design.op_batch` (screenshot within the first minute) while `design_agent_run.status='running'` and BEFORE any `design.checkpoint`; the pageless notice is gone at that moment.
4. Proof of item C: the run trace's first compile carries a `page` line; either no `*_refused_pageless` event appears (the prompt worked) or one appears with ZERO `image_generation_failed`/`image_registration_failed` after it (the guard worked). The run finishes with a repair round to spare (stop reason not `budget_exhausted_before_repair`).
5. Records: `_memory/2026-09-04-plan2-page-first-and-first-batch.md` + README index line; roadmap status header ticks Plan 2; ledger closed; SDD workspace removed.

---

### Task 5: Every ledgered operation reaches the stream (found by the Task 4 live proof)

**Why (verified 2026-09-04, run `run_b891860a…` / inner `run_8269352d…`):** the frontend cursor (`scene-stream-cursor.ts`, rule 5) applies an op frame only when it is CONTIGUOUS: `operations_total - operations.length === position`. The substrate appends to `self.operations_ledger` at 20 sites but only two of them push a frame (`compile_dsl_block`, `asset_placed`). On the fresh Apollo/Ramp document the compile auto-registered two kit assets (`brand_asset_registered`, ledger positions 1–2, no frame), so the first streamed batch ended at 20 with 18 ops and BEGAN at 2 while the cursor stood at 0 → dirty → every frame dropped until the first checkpoint. The stage kept the pageless notice for ~9 minutes although the frames had reached the browser (9 `design.op_batch` frames for the document, first at 11:00:05 IST). Task 3's canvas fix is correct but never got a frame to draw.

**Fix (one chokepoint, no per-site edits):** `record()` is the only place a frame is pushed, and `operations_ledger` is the only ledger. So when a `sink_extra` carries `operations` + `operations_total`, the frame PREPENDS every ledger operation that was appended since the last streamed frame; the frame then begins exactly where the client's cursor stands. A checkpoint re-seats the client at its committed position, so `checkpoint_scene` advances the same marker. The frame contract becomes "everything ledgered since the last frame you got", which is the contract the cursor already assumes.

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py` — `__init__` (~line 350, next to `self.operations_ledger`), `record()` (~line 4516; inside the lock, before `push` is built), `checkpoint_scene` (~line 4760, after `self._checkpointed_operations = len(operations)`).
- Modify: `subsystems/clue-design/apps/agent_runtime/tests/test_streaming_sink.py` — two existing position tests move to the new contract; three new tests.

**Interfaces:**
- Produces: `LumenDesignTools._streamed_ledger_len: int` (ledger entries the stream has carried so far) and `LumenDesignTools._contiguous_sink_extra(self, sink_extra: JsonObject) -> JsonObject`.
- Frontend unchanged (`scene-stream-cursor.ts` rule 5 already expects contiguity).

- [ ] **Step 1: Write the failing tests** (append to `test_streaming_sink.py`)

```python
# --- (d) Plan 2 Task 5: frames are contiguous with the ledger -------------------


def _upsert(asset_id):
    return {"kind": "upsert_asset", "asset": {"id": asset_id}}


def test_ops_ledgered_without_a_frame_ride_the_next_frame(tmp_path, monkeypatch):
    """The Apollo/Ramp shape: a compile auto-registers two kit assets (ledger 1–2, no frame)
    and then streams its own 3 ops ending at 5. The frame must BEGIN at 0 — the client's
    cursor — so it carries all five, the two registrations first."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _ThreeOpCore)
    from lumen_agent.tools.substrate import LumenDesignTools

    tools = LumenDesignTools(runtime_config(tmp_path), "design a launch poster")
    pushes = _attach_sink(tools)
    tools._log_scene_operations("brand_asset", [_upsert("asset_a"), _upsert("asset_b")])

    tools.compile_dsl_block('page Test\n  text "Plan"')

    push = _pushes_for(pushes, "dsl_compiled")[0]
    assert push["operations_total"] == 5
    assert [op["kind"] for op in push["operations"]] == [
        "upsert_asset", "upsert_asset", "add_page", "insert_node", "set_text",
    ]
    assert push["operations_total"] - len(push["operations"]) == 0


def test_a_second_frame_carries_only_its_own_ops(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _ThreeOpCore)
    from lumen_agent.tools.substrate import LumenDesignTools

    tools = LumenDesignTools(runtime_config(tmp_path), "design a launch poster")
    pushes = _attach_sink(tools)
    tools._log_scene_operations("brand_asset", [_upsert("asset_a")])
    tools.compile_dsl_block('page Test\n  text "Plan"')
    tools.compile_dsl_block('page Test2\n  text "Plan"')

    first, second = _pushes_for(pushes, "dsl_compiled")
    assert first["operations_total"] == 4 and len(first["operations"]) == 4
    assert second["operations_total"] == 7 and len(second["operations"]) == 3
    # Contiguous: the second frame begins exactly where the first ended.
    assert second["operations_total"] - len(second["operations"]) == first["operations_total"]


def test_a_checkpoint_advances_the_streamed_marker(tmp_path, monkeypatch):
    """Ops committed by a checkpoint are durable and the client reloads them (rung A), so a
    frame after the checkpoint must not re-carry them — it begins at the checkpoint's position."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _ThreeOpCore)
    from lumen_agent.tools.substrate import LumenDesignTools

    tools = LumenDesignTools(runtime_config(tmp_path), "design a launch poster")
    tools.scene_checkpoint = lambda operations, meta: None
    pushes = _attach_sink(tools)
    tools._log_scene_operations("brand_asset", [_upsert("asset_a"), _upsert("asset_b")])
    tools.checkpoint_scene("round_1")

    tools.compile_dsl_block('page Test\n  text "Plan"')

    push = _pushes_for(pushes, "dsl_compiled")[0]
    assert push["operations_total"] == 5
    assert len(push["operations"]) == 3
    assert push["operations_total"] - len(push["operations"]) == 2
```

Also move the two existing position tests to the new contract (their seeds are unstreamed ledger entries, so the next frame now carries them):
- `test_clean_compile_sink_push_carries_ledger_position`: `assert len(push["operations"]) == 11` with the comment `# 8 unstreamed seeds ride this frame ahead of the compile's 3 (Plan 2 Task 5).`; keep `operations_total == 11`.
- `test_asset_placement_sink_push_carries_ledger_position`: `assert len(push["operations"]) == 5` with the same-shaped comment; keep `operations_total == 5`.

- [ ] **Step 2: Run to verify failure**

Run (from `subsystems/clue-design`): `... pytest apps/agent_runtime/tests/test_streaming_sink.py -q -p no:cacheprovider`
Expected: the 3 new tests fail (frame carries only its own ops); the 2 edited ones fail (3 ≠ 11, 1 ≠ 5); the rest pass.

- [ ] **Step 3: Implement**

`__init__`, right after `self.operations_ledger: list[JsonObject] = []`:

```python
        #: Plan 2 Task 5: how much of `operations_ledger` the stream has carried. The client's
        #: cursor applies a frame only when it BEGINS where the cursor stands, so a frame must
        #: carry every ledger entry since the last frame — see `_contiguous_sink_extra`.
        self._streamed_ledger_len = 0
```

On the class, next to `record()`:

```python
    def _contiguous_sink_extra(self, sink_extra: JsonObject) -> JsonObject:
        """Make an op-bearing sink push begin where the client's cursor stands.

        `operations_ledger` grows at ~20 sites (asset registration, autofix, pruning, …) but only
        the authoring mutations push a frame. The frontend cursor (`scene-stream-cursor.ts`,
        rule 5) applies a frame only when `operations_total - len(operations)` equals the
        position it has been shown up to; a gap makes it dirty and it drops every frame until
        a checkpoint. Live-proven 2026-09-04: two auto-registered kit assets (ledger 1–2, no
        frame) left the fresh Apollo/Ramp document's first batch beginning at 2, and the stage
        showed nothing for nine minutes. So every frame prepends the ledger entries streamed
        since the last frame, and a checkpoint (which re-seats the client) advances the marker.
        """
        operations = sink_extra.get("operations")
        total = sink_extra.get("operations_total")
        if not isinstance(operations, list) or not isinstance(total, int):
            return sink_extra
        begin = total - len(operations)
        if begin > self._streamed_ledger_len:
            missing = [
                entry["operation"]
                for entry in self.operations_ledger[self._streamed_ledger_len : begin]
                if isinstance(entry, dict) and "operation" in entry
            ]
            operations = missing + list(operations)
        self._streamed_ledger_len = max(self._streamed_ledger_len, total)
        return {**sink_extra, "operations": operations}
```

In `record()`, inside `with self._record_lock:` and before `push` is built, replace `if sink_extra:` / `push.update(sink_extra)` with:

```python
                    if sink_extra:
                        push.update(self._contiguous_sink_extra(sink_extra))
```

In `checkpoint_scene`, immediately after `self._checkpointed_operations = len(operations)`:

```python
        # Plan 2 Task 5: the checkpoint re-seats the client at this position (rung A reloads
        # the version it names), so nothing before it needs to ride a later frame.
        self._streamed_ledger_len = max(self._streamed_ledger_len, len(operations))
```

- [ ] **Step 4: Run the sink tests and the neighbours**

Run: `... pytest apps/agent_runtime/tests/test_streaming_sink.py apps/agent_runtime/tests/test_scene_checkpoint.py apps/agent_runtime/tests/test_deepagent_harness.py apps/agent_runtime/tests/test_fast_loop.py -q -p no:cacheprovider`
Expected: all pass (record baseline counts for the three neighbour files BEFORE editing; they must match after).

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py subsystems/clue-design/apps/agent_runtime/tests/test_streaming_sink.py
git commit -m "fix(design-agent): op frames carry every ledgered operation since the last frame, so the canvas cursor stays contiguous"
```

Task 4 (live proof) is then re-run by the controller on a fresh document.
