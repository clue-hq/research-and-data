# Standalone Artifact Route Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Founder rules for SDD in this repo: implementers are **Opus** subagents only; review, verification, and rulings are the controller's. Commit locally, never push, no AI attribution.

**Goal:** The standalone artifact page (`/projects/{p}/artifacts/{id}`) honours the no-mid-run-editing rule exactly like the chat route: while a design run drives the open document, its Edit pill is refused with the lock's sentence, the inspector and canvas gestures are inert, the agent-working chip shows, and the canvas reloads when the run's commits change the document.

**Architecture:** A **document-scoped agent-busy signal**, the follow-up the editor surface's own comments record. The design API gains one read, `GET /documents/{document_id}/agent-run`, built on the very predicate the 409 uses (`active_design_run_for_document`) plus the document's `current_version`. The frontend polls it from the standalone editor surface (every 4 s while the tab is visible, paused when hidden), derives `sceneLocked` from `active`, threads it into the scene session and the stage through the props the chat route already uses, and bumps a reload nonce whenever `current_version` moves. No thread binding, no SSE, no new state elsewhere.

**Tech Stack:** FastAPI route + pytest (design API, shared Postgres under `ws_test_*`); React 19 hook + zod + node:test (`npx tsx --test`).

**Spec:** The finding in `_memory/2026-09-03-agent-working-chip.md` §Finding, and rung A of `docs/superpowers/plans/2026-09-02-scene-live-streaming.md` (the rule and the chat-route implementation this mirrors). The editor surface's three "deliberately NOT passed" comments (`editor-surface.tsx` ~lines 85-92, ~190, ~257-264) name this exact fix.

## Rulings taken in this plan (founder may override)

- **R1 Source of truth.** The lock on this route follows the design API's run row (`status = 'running'` for the document), i.e. the backend's own enforcement boundary, not the platform thread's leg state. Consequence: the seconds between a turn being accepted and its run row being claimed are unlocked here (the chat route locks earlier via its stream). A human write in that window is not lost: the run reads the current scene when it starts.
- **R2 Poll, not push.** 4 s interval, only while the page is visible. Cheap (one row read), no SSE subscription for a page that has no turn stream. Revisit if the run_event SSE becomes the standalone route's transport.
- **R3 Reload semantics.** `current_version` moving between polls bumps the canvas reload token (this also gives the standalone page checkpoint refreshes, which it never had); the release itself is just the last such move.

## Global Constraints

- Design API tests: from `subsystems/clue-design`, `set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest <file> -v`. They run against the shared colombo Postgres under a per-test `ws_test_*` workspace. Do not offer jobs to the fleet (none of this plan's tests do).
- Frontend gate: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`; tests are node:test via `npx tsx --test`. Not vitest. No DOM in tests; hook logic lives in a pure module.
- Reuse, never re-implement: the 409's predicate `repo.active_design_run_for_document`, `require_document`, the lock's ratified copy `AGENT_RUN_LOCK_NOTE`, `designBffConfig()` + `defaultDesignFetch`, and `ArtifactStage`'s existing `editDisabled` / `editDisabledReason` / `inspectorDisabled` / `sceneGestureDisabled` props.
- No env flag, no migration, no Rust. Commit per task; no `Co-Authored-By`, no AI attribution. Never push, never `git stash`, work only in this worktree.

---

### Task 1: `GET /documents/{document_id}/agent-run` on the design API

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (add the route directly after `get_document`, the `@app.get("/documents/{document_id}")` handler)
- Test: `subsystems/clue-design/apps/api/tests/test_document_agent_run_read.py`

**Interfaces:**
- Consumes: `require_document(repo, document_id)` (raises the 404 the other document routes raise), `HybridRepository.active_design_run_for_document(document_id) -> str | None`, the seeding helpers `create_document`, `start_leg_run`, `finish_run` from `tests/test_agent_run_write_lock.py` (importable: the tests directory is on `sys.path`, as `from conftest import …` shows).
- Produces: `GET /documents/{document_id}/agent-run` → `{"schema_version": 1, "document_id": str, "active": bool, "run_id": str | null, "current_version": int}`; 404 for an unknown document (same shape as the document GET's 404).

- [x] **Step 1: Write the failing tests**

Create `subsystems/clue-design/apps/api/tests/test_document_agent_run_read.py`:

```python
"""The document-scoped agent-busy read (scene live-streaming rung A follow-up, 2026-09-03).

The standalone artifact route has no turn stream, so it asks the design API directly whether a
run is driving the document — the SAME predicate the manual-write routes' 409 uses, so the
page's lock and the server's refusal can never disagree about which state they are in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from test_agent_run_write_lock import create_document, finish_run, start_leg_run


@pytest.fixture(autouse=True)
def _no_embedded_fleet_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same reason as the write-lock suite: a seeded run must stay exactly where the test put it.
    monkeypatch.setenv("LUMEN_FLEET_EMBEDDED_WORKER", "0")


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache"))


def read_agent_run(client: TestClient, document_id: str) -> dict:
    response = client.get(f"/documents/{document_id}/agent-run")
    assert response.status_code == 200, response.text
    return response.json()


def test_an_idle_document_reports_no_run_and_its_current_version(client: TestClient) -> None:
    document = create_document(client, "Idle")
    body = read_agent_run(client, document["id"])
    assert body["schema_version"] == 1
    assert body["document_id"] == document["id"]
    assert body["active"] is False
    assert body["run_id"] is None
    assert body["current_version"] == document["current_version"]


def test_a_running_run_is_reported_and_clears_when_it_finishes(client: TestClient) -> None:
    document = create_document(client, "Driven")
    store = HybridRepository()
    run_id = start_leg_run(store, document["id"])

    busy = read_agent_run(client, document["id"])
    assert busy["active"] is True
    assert busy["run_id"] == run_id

    finish_run(store, run_id)
    idle = read_agent_run(client, document["id"])
    assert idle["active"] is False
    assert idle["run_id"] is None


def test_a_run_on_another_document_does_not_lock_this_one(client: TestClient) -> None:
    driven = create_document(client, "Driven")
    bystander = create_document(client, "Bystander")
    store = HybridRepository()
    run_id = start_leg_run(store, driven["id"])
    try:
        assert read_agent_run(client, bystander["id"])["active"] is False
        assert read_agent_run(client, driven["id"])["run_id"] == run_id
    finally:
        finish_run(store, run_id)


def test_an_unknown_document_is_a_404(client: TestClient) -> None:
    response = client.get("/documents/doc_does_not_exist/agent-run")
    assert response.status_code == 404, response.text
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_document_agent_run_read.py -v`
Expected: the three 200-path tests fail with `404` (route missing); the 404 test passes trivially. If `from test_agent_run_write_lock import …` fails to import, check that suite's own fixture name for the embedded-worker env var and copy its exact `monkeypatch.setenv` line; report what you found.

- [x] **Step 3: Add the route**

In `main.py`, directly after the `get_document` handler:

```python
    @app.get("/documents/{document_id}/agent-run")
    def get_document_agent_run(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        """The document-scoped agent-busy signal (scene live-streaming rung A follow-up).

        The standalone artifact route has no turn stream to derive the editor lock from, so it
        asks HERE — the same ``active_design_run_for_document`` predicate the manual-write routes'
        409 reads, so the page's lock and the server's refusal cannot disagree. ``current_version``
        rides along so a poller can reload the canvas when the run's commits move the document,
        without a second request.
        """
        document = require_document(repo, document_id)
        run_id = repo.active_design_run_for_document(document_id)
        return {
            "schema_version": 1,
            "document_id": document_id,
            "active": run_id is not None,
            "run_id": run_id,
            "current_version": document["current_version"],
        }
```

- [x] **Step 4: Run the tests to verify they pass, plus the write-lock suite**

Run the new file, then `apps/api/tests/test_agent_run_write_lock.py` (it must be unaffected). Expected: 4 passed; write-lock suite all passed.

- [x] **Step 5: Commit**

```
git add subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_document_agent_run_read.py
git commit -m "feat(design-api): GET /documents/{id}/agent-run — the document-scoped agent-busy read

The standalone artifact route has no turn stream to derive the editor lock from. This read
answers from the same predicate the manual-write routes' 409 uses, plus current_version so a
poller can reload the canvas when the run's commits move the document."
```

---

### Task 2: The standalone editor surface polls the read and locks

**Files:**
- Create: `apps/frontend/src/features/design-editor/data/document-agent-run.ts`
- Create: `apps/frontend/src/features/design-editor/hooks/document-agent-run.logic.ts`
- Create: `apps/frontend/src/features/design-editor/hooks/use-document-agent-run.ts`
- Create: `apps/frontend/src/features/design-editor/hooks/document-agent-run.test.ts`
- Modify: `apps/frontend/src/features/chat-shell/components/editor-surface.tsx`

**Interfaces:**
- Consumes: Task 1's read; `designBffConfig()` from `@/features/design-editor/data/design-bff`; `AGENT_RUN_LOCK_NOTE` from `@/features/chat-shell/model/agent-run-lock`; `useSceneEditingSession`'s `agentRunLocked` option; `ArtifactStage`'s `editDisabled`, `editDisabledReason`, `inspectorDisabled`, `sceneGestureDisabled`, `canvasReloadToken` props (the chat route passes all of them; see `chat-surface.tsx` lines ~583, ~792, ~830-831).
- Produces:
  - `DocumentAgentRun = { active: boolean; runId: string | null; currentVersion: number }` and `fetchDocumentAgentRun(config: { apiBaseUrl: string; fetchImpl?: typeof fetch }, documentId: string): Promise<DocumentAgentRun>` (zod-validated; throws on non-200 or bad shape).
  - `reduceAgentRunPoll(previous: AgentRunPollState, next: DocumentAgentRun): AgentRunPollState` where `AgentRunPollState = { active: boolean; runId: string | null; currentVersion: number | null; reloadNonce: number }` and `INITIAL_AGENT_RUN_POLL: AgentRunPollState`. Rule: `reloadNonce` increments iff `previous.currentVersion !== null && next.currentVersion !== previous.currentVersion`; `active`/`runId`/`currentVersion` are copied from `next`.
  - `useDocumentAgentRun({ documentId, enabled, intervalMs = 4000 }): AgentRunPollState` — polls while `enabled && documentId` and `document.visibilityState === "visible"`; first poll immediately on mount/`documentId` change; resets to `INITIAL_AGENT_RUN_POLL` when `documentId` changes; a failed poll keeps the previous state (the lock errs toward its last known answer, and the next tick retries); clears its interval on unmount.

- [x] **Step 1: Write the failing tests**

Create `apps/frontend/src/features/design-editor/hooks/document-agent-run.test.ts`:

```ts
import assert from "node:assert/strict";
import { it } from "node:test";
import { fetchDocumentAgentRun } from "../data/document-agent-run";
import { INITIAL_AGENT_RUN_POLL, reduceAgentRunPoll } from "./document-agent-run.logic";

const idle = { active: false, runId: null, currentVersion: 3 };
const busy = { active: true, runId: "run_1", currentVersion: 3 };

it("copies the read and starts with no reload", () => {
  const first = reduceAgentRunPoll(INITIAL_AGENT_RUN_POLL, busy);
  assert.deepEqual(first, { active: true, runId: "run_1", currentVersion: 3, reloadNonce: 0 });
});

it("bumps the reload nonce exactly when current_version moves", () => {
  const a = reduceAgentRunPoll(INITIAL_AGENT_RUN_POLL, busy);
  const b = reduceAgentRunPoll(a, busy); // same version — no bump
  assert.equal(b.reloadNonce, 0);
  const c = reduceAgentRunPoll(b, { ...busy, currentVersion: 4 }); // a checkpoint landed
  assert.equal(c.reloadNonce, 1);
  const d = reduceAgentRunPoll(c, { ...idle, currentVersion: 5 }); // the run finished and committed
  assert.equal(d.reloadNonce, 2);
  assert.equal(d.active, false);
  assert.equal(d.runId, null);
});

it("does not treat the first observed version as a change", () => {
  const first = reduceAgentRunPoll(INITIAL_AGENT_RUN_POLL, { ...idle, currentVersion: 9 });
  assert.equal(first.reloadNonce, 0);
});

it("fetches and validates the agent-run read through the configured transport", async () => {
  const calls: string[] = [];
  const fetchImpl: typeof fetch = async (input) => {
    calls.push(String(input instanceof URL ? input.pathname : input));
    return new Response(
      JSON.stringify({ schema_version: 1, document_id: "doc_1", active: true, run_id: "run_9", current_version: 12 }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  const result = await fetchDocumentAgentRun({ apiBaseUrl: "http://design.test", fetchImpl }, "doc_1");
  assert.deepEqual(result, { active: true, runId: "run_9", currentVersion: 12 });
  assert.deepEqual(calls, ["/documents/doc_1/agent-run"]);
});

it("rejects a non-200 and a malformed body", async () => {
  const notFound: typeof fetch = async () => new Response("{}", { status: 404 });
  await assert.rejects(fetchDocumentAgentRun({ apiBaseUrl: "http://design.test", fetchImpl: notFound }, "doc_x"));
  const malformed: typeof fetch = async () =>
    new Response(JSON.stringify({ active: "yes" }), { status: 200, headers: { "content-type": "application/json" } });
  await assert.rejects(fetchDocumentAgentRun({ apiBaseUrl: "http://design.test", fetchImpl: malformed }, "doc_x"));
});
```

- [x] **Step 2: Run the tests to verify they fail**

From `apps/frontend`: `npx tsx --test src/features/design-editor/hooks/document-agent-run.test.ts` → module-not-found failures.

- [x] **Step 3: Write the data read**

Create `apps/frontend/src/features/design-editor/data/document-agent-run.ts`:

```ts
import { z } from "zod";
import { defaultDesignFetch } from "../engine/config";

/**
 * `GET /documents/{id}/agent-run` — the document-scoped agent-busy read (scene
 * live-streaming rung A follow-up). Answers from the same predicate the design
 * API's manual-write 409 uses, so a page that locks on it can never disagree
 * with the server about whether a run is driving the document.
 */
const documentAgentRunWire = z.object({
  schema_version: z.literal(1),
  document_id: z.string().min(1),
  active: z.boolean(),
  run_id: z.string().min(1).nullable(),
  current_version: z.number().int().nonnegative(),
});

export interface DocumentAgentRun {
  active: boolean;
  runId: string | null;
  currentVersion: number;
}

export async function fetchDocumentAgentRun(
  // Workspace auth is the BFF's job — callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: { apiBaseUrl: string; fetchImpl?: typeof fetch },
  documentId: string,
): Promise<DocumentAgentRun> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/agent-run`, apiBaseUrl),
  );
  if (!response.ok) {
    throw new Error(`agent-run read failed for ${documentId} (HTTP ${response.status})`);
  }
  const wire = documentAgentRunWire.parse(await response.json());
  return { active: wire.active, runId: wire.run_id, currentVersion: wire.current_version };
}
```

(If `defaultDesignFetch` lives elsewhere than `../engine/config`, import it from where `documentStore.ts` does and say so.)

- [x] **Step 4: Write the pure poll reducer**

Create `apps/frontend/src/features/design-editor/hooks/document-agent-run.logic.ts`:

```ts
import type { DocumentAgentRun } from "../data/document-agent-run";

/** What the standalone editor surface knows about the run driving its document. */
export interface AgentRunPollState {
  active: boolean;
  runId: string | null;
  /** `null` until the first successful read — the first observed version is a
   * baseline, never a change. */
  currentVersion: number | null;
  /** Increments each time `current_version` moves between reads: a checkpoint
   * landed, or the run finished and committed. The surface adds it to the
   * canvas reload token, which is how this route gets the reloads the chat
   * route gets from `design.checkpoint` frames. */
  reloadNonce: number;
}

export const INITIAL_AGENT_RUN_POLL: AgentRunPollState = {
  active: false,
  runId: null,
  currentVersion: null,
  reloadNonce: 0,
};

export function reduceAgentRunPoll(
  previous: AgentRunPollState,
  next: DocumentAgentRun,
): AgentRunPollState {
  const moved =
    previous.currentVersion !== null && next.currentVersion !== previous.currentVersion;
  return {
    active: next.active,
    runId: next.runId,
    currentVersion: next.currentVersion,
    reloadNonce: moved ? previous.reloadNonce + 1 : previous.reloadNonce,
  };
}
```

- [x] **Step 5: Write the hook**

Create `apps/frontend/src/features/design-editor/hooks/use-document-agent-run.ts`:

```ts
import { useEffect, useState } from "react";
import { designBffConfig } from "../data/design-bff";
import { fetchDocumentAgentRun } from "../data/document-agent-run";
import {
  INITIAL_AGENT_RUN_POLL,
  reduceAgentRunPoll,
  type AgentRunPollState,
} from "./document-agent-run.logic";

const DEFAULT_INTERVAL_MS = 4000;

/**
 * Poll the document-scoped agent-busy read for the standalone artifact route
 * (ruling R2: poll, not push — this route has no turn stream). Polls only while
 * enabled and the tab is visible; the first read fires immediately; a failed read
 * keeps the last answer (the lock errs toward what it last knew, and the next
 * tick retries). State resets when the document changes.
 */
export function useDocumentAgentRun({
  documentId,
  enabled,
  intervalMs = DEFAULT_INTERVAL_MS,
}: {
  documentId: string | null;
  enabled: boolean;
  intervalMs?: number;
}): AgentRunPollState {
  const [state, setState] = useState<AgentRunPollState>(INITIAL_AGENT_RUN_POLL);

  useEffect(() => {
    setState(INITIAL_AGENT_RUN_POLL);
    if (!enabled || !documentId) {
      return;
    }
    let cancelled = false;
    let interval: number | null = null;
    const config = designBffConfig();

    const poll = async () => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") {
        return;
      }
      try {
        const next = await fetchDocumentAgentRun(config, documentId);
        if (!cancelled) {
          setState((previous) => reduceAgentRunPoll(previous, next));
        }
      } catch {
        // Keep the last answer; the next tick retries.
      }
    };

    void poll();
    interval = window.setInterval(() => void poll(), intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") void poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      if (interval !== null) window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [documentId, enabled, intervalMs]);

  return state;
}
```

- [x] **Step 6: Wire the editor surface**

In `editor-surface.tsx`:

1. Imports: `import { AGENT_RUN_LOCK_NOTE } from "@/features/chat-shell/model/agent-run-lock";` and `import { useDocumentAgentRun } from "@/features/design-editor/hooks/use-document-agent-run";`.
2. Before the `useSceneEditingSession` call, derive the document id the way the chat route does (`documentIds?.[activeArtifactId] ?? null`) and poll:
   ```tsx
   const sceneDocumentId =
     controller.artifactKind === "ad" && controller.activeArtifactId
       ? (documentIds?.[controller.activeArtifactId] ?? null)
       : null;
   const agentRun = useDocumentAgentRun({
     documentId: sceneDocumentId,
     enabled: controller.artifactKind === "ad",
   });
   const sceneLocked = agentRun.active;
   ```
3. Pass `agentRunLocked: sceneLocked` to `useSceneEditingSession`, REPLACING the "deliberately NOT passed" comment there with a two-line note that the lock now comes from the document-scoped agent-busy read (`useDocumentAgentRun`), ruling R1 of this plan.
4. Where the inspector is rendered (the `inspectorDisabled` comment ~line 190), pass `inspectorDisabled={sceneLocked}` exactly as `chat-surface.tsx` does at its line ~583, and replace that comment likewise.
5. On `<ArtifactStage …>`: add `sceneGestureDisabled={sceneLocked}`, `editDisabled={sceneLocked && !controller.editing}`, `editDisabledReason={AGENT_RUN_LOCK_NOTE}`, and change `canvasReloadToken` to `session.reloadNonce + sceneSession.reloadNonce + agentRun.reloadNonce`. Replace the "deliberately NOT passed" comment beside `sceneGestureDisabled` with the same two-line note.

The agent-working chip needs nothing: it already renders from `editDisabled`.

- [x] **Step 7: Tests and gate**

From `apps/frontend`: `npx tsx --test src/features/design-editor/hooks/document-agent-run.test.ts` → 5 pass. Then `npm run design-system:build && npm run lint && npm run build` (lint: only the two pre-existing `canvasOperations.ts` warnings). Then the chat-shell + design-editor suites: `find src/features/chat-shell src/features/design-editor \( -name "*.test.ts" -o -name "*.test.tsx" \) -print0 | xargs -0 npx tsx --test` → all pass.

- [x] **Step 8: Commit**

```
git add apps/frontend/src/features/design-editor/data/document-agent-run.ts apps/frontend/src/features/design-editor/hooks/document-agent-run.logic.ts apps/frontend/src/features/design-editor/hooks/use-document-agent-run.ts apps/frontend/src/features/design-editor/hooks/document-agent-run.test.ts apps/frontend/src/features/chat-shell/components/editor-surface.tsx
git commit -m "feat(chat-shell): the standalone artifact route locks on the document-scoped agent-busy read

The page had no turn stream, so rung A's lock never reached it: during a run its Edit pill
was live and only the server's 409 stood between the user and a write. It now polls
GET /documents/{id}/agent-run (4 s, visible tab only), locks the session, inspector, gestures
and Edit pill exactly as the chat route does, shows the agent-working chip, and reloads the
canvas whenever the run's commits move current_version."
```

Live check (controller): start a design turn on the Apollo thread, open `/projects/{p}/artifacts/{doc}` directly: chip visible, Edit pill refused with the tooltip, inspector closed; after the run releases: chip gone within one poll, canvas shows the run's change without a manual reload.
