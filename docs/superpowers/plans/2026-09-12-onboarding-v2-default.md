# Onboarding V2 As Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Welcome flow's setting-up screen runs the new onboarding lane (`POST /onboarding`, `GET /onboarding/current`) instead of the old Stage-0 recon, and releases the user into the app when the four fast steps are done.

**Architecture:** The frontend's setup data seam switches to the two new endpoints through the existing `/api/clue` BFF proxy and parses the new run/steps shape into a `SetupStatus` whose `complete`/`failed` are derived from the fast-phase steps. The checklist rows map onto step kinds instead of Client-KB field keys; the brand-kit row keeps reading the ingestion job. The release, stall and error lifecycle in `useSetupProgress` is untouched. Backend: onboarding v2 defaults on, and the old Stage-0 recon composes only behind its own legacy flag, so provisioning no longer drags the old lane in.

**Tech Stack:** Next.js / TypeScript / Zod / node:test (frontend), Python 3.13 / pydantic-settings / FastAPI composition roots (backend), pytest offline suites.

**Spec:** `docs/superpowers/specs/archive/2026-09-12-onboarding-v2-default-design.md`

## Global Constraints

- Release into the app as soon as the four fast steps (`overview`, `lineup`, `reviews`, `synthesis`) are terminal and none failed (founder ruling 2026-09-12). Personas and per-product research continue in the background.
- No visual change to the setting-up screen: the frozen `SetupItem` vocabulary (`complete | running | queued`), the same component tree. Row copy is integration-authored pending founder review (state that in the row table's comment, as the old table did).
- Every flag in `.env.example` with its default in the same commit; lane `.env` at parity. The parity check is `tests/arv2/test_settings.py`-style: assert the env line exists.
- Never delete the old Stage-0 code (section G of the ledger retires it later); only its composition moves behind `CLUE_LEGACY_STAGE0_RECON_ENABLED`.
- Offline suites without `.env`; DB suites on the lane DB only, with `-p no:cacheprovider`. No AI attribution. Never push.
- Frontend gates: `npm test`, `npm run lint`, `npx tsc --noEmit -p .` (50-error baseline), `npm run build` at the end.

The new lane's wire vocabulary, verbatim from the migrations: step `kind ∈ {overview, lineup, catalog_sync, reviews, synthesis, product_research, persona}`, `phase ∈ {fast, background}`, step `status ∈ {queued, running, completed, empty, failed}`, run `status ∈ {queued, running, completed, failed, …}` (the `GET /onboarding/current` body is `{ schema_version, runId, status, steps[{kind, subjectRef, phase, status, startedAt, finishedAt, costUsd, failureCode}], costUsd }`, and `status: "none"` with `runId: null` when no run exists).

---

## File map

| File | Responsibility |
|---|---|
| `libs/clue-config/clue_config/settings.py` | `onboarding_v2_enabled` default `True`; new `legacy_stage0_recon_enabled` (default `False`) |
| `.env.example`, `.env` | the two lines |
| `tests/api/test_onboarding_flags.py` | defaults + parity |
| `platform/api/clue_api/projections_main.py` | scrape binder composes behind the legacy flag |
| `platform/api/clue_api/projections_app.py` | Stage-0 setup router mounts behind the legacy flag |
| `platform/api/clue_api/fleet_main.py` | recon handler + binder behind the legacy flag |
| `tests/api/test_extractor_composition.py`, `tests/api/test_stage0_setup_db.py`, `tests/api/test_brand_kit_onboarding_ingestion_db.py` | flag rename in the composition tests |
| `apps/frontend/src/features/onboarding/data/setup.ts` | new `SetupStatusSchema`, new endpoints |
| `apps/frontend/src/features/onboarding/data/setup.test.ts` | parse + call tests |
| `apps/frontend/src/features/onboarding/data/setup-groups.ts` | rows keyed by step kinds |
| `apps/frontend/src/features/onboarding/model/setup-items.ts` | derivation over steps |
| `apps/frontend/src/features/onboarding/model/setup-items.test.ts` | its tests |
| `apps/frontend/src/features/onboarding/model/setup-stall.ts` | signature over steps |
| `apps/frontend/src/features/onboarding/model/setup-stall.test.ts` | its tests |
| `apps/frontend/src/features/onboarding/data/setup-progress.fixture.ts` | new-shape frames |
| `apps/frontend/src/features/onboarding/data/setup-progress.repository.test.ts` | fixture stream test |
| `apps/frontend/src/features/onboarding/data/onboarding.fixture.ts` | the setup rows' identities |
| `apps/frontend/src/features/onboarding/hooks/use-setup-progress.ts` | unchanged lifecycle; reads `company_website` for the start |
| `apps/frontend/docs/api-contracts/onboarding.md` (create if absent) | contract note |

---

### Task 1: The flags

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (~line 400 `onboarding_v2_enabled`; ~line 703 after `self_serve_provisioning_enabled`)
- Modify: `.env.example` (~line 121 and ~line 191), `.env` (parity)
- Create: `tests/api/test_onboarding_flags.py`

**Interfaces:**
- Produces: `Settings.onboarding_v2_enabled: bool = True`; `Settings.legacy_stage0_recon_enabled: bool = False` (env `CLUE_LEGACY_STAGE0_RECON_ENABLED`).

- [ ] **Step 1: Write the failing test**

```python
"""The onboarding lane is the default; the old Stage-0 recon composes only behind its own flag."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CLUE_ONBOARDING_V2_ENABLED", "CLUE_LEGACY_STAGE0_RECON_ENABLED", "CLUE_SELF_SERVE_PROVISIONING_ENABLED"):
        monkeypatch.delenv(name, raising=False)


def test_the_new_lane_is_on_and_the_old_recon_is_off_by_default(clean_env: None) -> None:
    settings = Settings(_env_file=None)
    assert settings.onboarding_v2_enabled is True
    assert settings.legacy_stage0_recon_enabled is False
    # Provisioning alone no longer implies the old recon (ledger A4).
    assert Settings(_env_file=None, self_serve_provisioning_enabled=True).legacy_stage0_recon_enabled is False


def test_both_flags_are_documented_with_their_defaults() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert re.search(r"^CLUE_ONBOARDING_V2_ENABLED=true$", text, re.MULTILINE)
    assert re.search(r"^CLUE_LEGACY_STAGE0_RECON_ENABLED=false$", text, re.MULTILINE)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/api/test_onboarding_flags.py -q -p no:cacheprovider`
Expected: FAIL — `onboarding_v2_enabled` is `False`; no `legacy_stage0_recon_enabled`.

- [ ] **Step 3: Implement**

In `settings.py`, change the onboarding block to:

```python
    # --- ARV2 onboarding lane (Track O; ARV2-ONBOARDING-PLAN.md §10) --------------------------
    # Routes ``POST /onboarding`` to the new fleet driver (O3). ON by default since 2026-09-12
    # (spec 2026-09-12-onboarding-v2-default): the Welcome flow's setting-up screen runs this
    # lane. Env: ``CLUE_ONBOARDING_V2_ENABLED``.
    onboarding_v2_enabled: bool = True
```

After `self_serve_provisioning_enabled`:

```python
    # The OLD Stage-0 recon (scrape binder, ``/stage0/setup``, the STAGE0_RECON fleet handler and
    # the official-site crawl). Until 2026-09-12 it composed whenever provisioning was on, which
    # meant "provisioning on" = "old lane on" (ledger A4). It now composes only behind this flag,
    # default off, until section G of the ledger retires the code. Env:
    # ``CLUE_LEGACY_STAGE0_RECON_ENABLED``.
    legacy_stage0_recon_enabled: bool = False
```

In `.env.example`, replace the four-line block around `CLUE_SELF_SERVE_PROVISIONING_ENABLED` with:

```
# Gates POST /auth/v1/provision (self-serve workspace creation) and nothing else since 2026-09-12.
CLUE_SELF_SERVE_PROVISIONING_ENABLED=false
# The OLD Stage-0 recon (/stage0/setup, the STAGE0_RECON handler, the scrape binder, the
# official-site crawl). Off: the Welcome flow runs the new onboarding lane. Kept until the old
# code is retired (defect ledger §G).
CLUE_LEGACY_STAGE0_RECON_ENABLED=false
```

and make sure `CLUE_ONBOARDING_V2_ENABLED=true` (it already is at line ~191; keep it). Add `CLUE_LEGACY_STAGE0_RECON_ENABLED=false` to the lane `.env` beside the provisioning line.

- [ ] **Step 4: Run; ruff**

Run: `.venv/bin/pytest tests/api/test_onboarding_flags.py tests/arv2/test_settings.py -q -p no:cacheprovider && .venv/bin/ruff check libs/clue-config tests/api/test_onboarding_flags.py`
Expected: PASS, clean. If a settings test elsewhere pins `onboarding_v2_enabled is False` (search `onboarding_v2_enabled` under `tests/`), update it to `True` with a one-line reason.

- [ ] **Step 5: Commit**

```bash
git add libs/clue-config/clue_config/settings.py .env.example tests/api/test_onboarding_flags.py
git commit -m "feat(config): onboarding v2 on by default; the old Stage-0 recon composes only behind CLUE_LEGACY_STAGE0_RECON_ENABLED"
```

---

### Task 2: Move the old recon's composition behind the legacy flag

**Files:**
- Modify: `platform/api/clue_api/projections_main.py:105` (`if resolved.self_serve_provisioning_enabled:` → legacy flag) and `:244` (the registry-seeding condition: keep provisioning **or** legacy **or** research views — the new lane's onboarding does not read the source manifests, but provisioning still mints a brand and the old condition is harmless; change it to `resolved.legacy_stage0_recon_enabled or research_views is not None`)
- Modify: `platform/api/clue_api/projections_app.py:923` (`if resolved.self_serve_provisioning_enabled and ingestion_storage is not None:` → `if resolved.legacy_stage0_recon_enabled and ingestion_storage is not None:`)
- Modify: `platform/api/clue_api/fleet_main.py:550` (`if not settings.self_serve_provisioning_enabled: return None` → legacy flag) and `:1163` (`if settings.self_serve_provisioning_enabled` → legacy flag)
- Modify tests: `tests/api/test_extractor_composition.py` (every `self_serve_provisioning_enabled=` in the extractor/binder tests → `legacy_stage0_recon_enabled=`), `tests/api/test_stage0_setup_db.py:1110` (`{"self_serve_provisioning_enabled": enabled}` → `{"legacy_stage0_recon_enabled": enabled}`), `tests/api/test_brand_kit_onboarding_ingestion_db.py:498` (add `legacy_stage0_recon_enabled=True` beside the provisioning flag if that test exercises `/stage0/setup`; leave it if it only provisions — read the test to decide and say which in the commit)

**Interfaces:**
- Produces: with `CLUE_SELF_SERVE_PROVISIONING_ENABLED=true` and the legacy flag off, `build_application` composes **no** scrape binder, mounts **no** `/stage0/setup`, and the fleet composes **no** `Stage0ReconWorkHandler`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_extractor_composition.py`:

```python
def test_provisioning_on_no_longer_composes_the_old_recon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ledger A4: provisioning mints workspaces; the old Stage-0 recon is its own switch now."""
    monkeypatch.setattr(run_composition, "Secrets", _NoKeySecrets)
    seen = _captured_extractor(monkeypatch, projections_main)
    projections_main.build_application(
        _settings(tmp_path, self_serve_provisioning_enabled=True, legacy_stage0_recon_enabled=False),
        secrets=Secrets(_env_file=None),
    )
    assert seen == {}
    assert (
        fleet_main._build_stage0_scrape_binder(
            _settings(tmp_path, self_serve_provisioning_enabled=True, legacy_stage0_recon_enabled=False),
            gateway=_FakeGateway(),
        )
        is None
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/api/test_extractor_composition.py -q -p no:cacheprovider -k no_longer_composes`
Expected: FAIL — the extractor was captured / the binder is not `None`.

- [ ] **Step 3: Flip the four composition sites and the tests**

Make the edits listed under **Files** (each is a one-token change of the condition; keep every surrounding comment and add one line above each: `# 2026-09-12: the old recon is its own switch (ledger A4); provisioning no longer implies it.`). Update the three test files' flag names as listed.

- [ ] **Step 4: Run the composition suites**

Run: `.venv/bin/pytest tests/api/test_extractor_composition.py -q -p no:cacheprovider` then `set -a; source .env; set +a; .venv/bin/pytest tests/api/test_stage0_setup_db.py tests/api/test_brand_kit_onboarding_ingestion_db.py -q -p no:cacheprovider`
Expected: PASS. Then ruff/mypy on the three touched modules.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/projections_main.py platform/api/clue_api/projections_app.py platform/api/clue_api/fleet_main.py tests/api/test_extractor_composition.py tests/api/test_stage0_setup_db.py tests/api/test_brand_kit_onboarding_ingestion_db.py
git commit -m "refactor(composition): the old Stage-0 recon composes behind CLUE_LEGACY_STAGE0_RECON_ENABLED, not provisioning (ledger A4)"
```

---

### Task 3: The data seam — new endpoints, new `SetupStatus`

**Files:**
- Modify: `apps/frontend/src/features/onboarding/data/setup.ts`
- Modify: `apps/frontend/src/features/onboarding/data/setup.test.ts`

**Interfaces:**
- Produces:

```ts
export const SetupStepSchema = z.object({
  kind: z.string(), subjectRef: z.string().nullable(), phase: z.enum(["fast","background"]).catch("background"),
  status: z.enum(["queued","running","completed","empty","failed"]).catch("running"),
  startedAt: z.string().nullable(), finishedAt: z.string().nullable(), costUsd: z.string(), failureCode: z.string().nullable(),
});
export const SetupStatusSchema = z.object({
  status: z.enum(["unavailable","none","starting","running","complete","failed"]).catch("unavailable"),
  run_id: z.string().nullable(), steps: z.array(SetupStepSchema).default([]),
  brand_kit_ingestion: SetupBrandKitIngestionSchema.nullable().optional().default(null),
});
export function setupStatusFromOnboarding(wire: unknown): SetupStatus   // parses the GET /onboarding/current body and derives `status`
export async function startWorkspaceSetup(input: { companyWebsite: string }): Promise<void>  // POST /api/clue/onboarding
export async function readSetupStatus(): Promise<SetupStatus>                                 // GET /api/clue/onboarding/current
export const FAST_STEP_KINDS = ["overview", "lineup", "reviews", "synthesis"] as const;
```

Derivation (`setupStatusFromOnboarding`): wire `status: "none"` → `none`; run `queued` → `starting`; run `running` → `complete` if every step whose `kind ∈ FAST_STEP_KINDS` exists with status `completed | empty`, else `failed` if any fast step is `failed`, else `running`; run `completed` → `complete`; run `failed` → `failed`; anything else → `unavailable`. `brand_kit_ingestion` stays `null` (Task 5 wires it if the new route ever serves it; today the brand-kit row reads the ingestion job through the existing `GET /api/clue/design/...` path only if that read exists — see Task 5).

- [ ] **Step 1: Write the failing tests** (replace the old-shape tests in `setup.test.ts`; keep the file's `fetch` stubbing helper)

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { FAST_STEP_KINDS, SetupStatusSchema, readSetupStatus, setupStatusFromOnboarding, startWorkspaceSetup } from "./setup";

function step(kind: string, status: string, phase = "fast") {
  return { kind, subjectRef: null, phase, status, startedAt: null, finishedAt: null, costUsd: "0", failureCode: null };
}
const running = { schema_version: "1", runId: "run-1", status: "running", costUsd: "0.10", steps: [] as unknown[] };

test("no run yet is none; a queued run is starting", () => {
  assert.equal(setupStatusFromOnboarding({ schema_version: "1", runId: null, status: "none", steps: [], costUsd: "0" }).status, "none");
  assert.equal(setupStatusFromOnboarding({ ...running, status: "queued" }).status, "starting");
});

test("the run is complete for the screen when every fast step is terminal and none failed", () => {
  const steps = FAST_STEP_KINDS.map((kind) => step(kind, "completed"));
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "complete");
  // `empty` is a correct outcome, not a failure.
  steps[2] = step("reviews", "empty");
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "complete");
  // Background work still running does not hold the release.
  assert.equal(setupStatusFromOnboarding({ ...running, steps: [...steps, step("persona", "running", "background")] }).status, "complete");
});

test("a fast step still running keeps the screen running; a failed fast step fails it", () => {
  const steps = [step("overview", "completed"), step("lineup", "running"), step("reviews", "queued"), step("synthesis", "queued")];
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "running");
  steps[1] = step("lineup", "failed");
  assert.equal(setupStatusFromOnboarding({ ...running, steps }).status, "failed");
});

test("an unknown run status degrades to unavailable rather than breaking the poll", () => {
  assert.equal(setupStatusFromOnboarding({ ...running, status: "paused" }).status, "unavailable");
});

test("start posts the company domain to the new lane and read parses the new shape", async (t) => {
  const calls: { url: string; init?: RequestInit }[] = [];
  t.mock.method(globalThis, "fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.endsWith("/api/clue/onboarding")) return new Response(JSON.stringify({ schema_version: "1", run_id: "run-1", status: "queued" }), { status: 202 });
    return new Response(JSON.stringify(running), { status: 200 });
  });
  await startWorkspaceSetup({ companyWebsite: "https://Insighthealth.ai/" });
  assert.equal(calls[0].url, "/api/clue/onboarding");
  assert.equal(calls[0].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { company_domain: "insighthealth.ai", brand_id: null });
  const status = await readSetupStatus();
  assert.equal(calls[1].url, "/api/clue/onboarding/current");
  assert.equal(status.status, "running");
  assert.equal(status.run_id, "run-1");
});

test("a 409 onboarding_in_progress on start is not a failure: the run is already running", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    new Response(JSON.stringify({ detail: { error: "onboarding_in_progress", reason: "run-0" } }), { status: 409 }),
  );
  await startWorkspaceSetup({ companyWebsite: "insighthealth.ai" }); // resolves, does not throw
});

test("the parsed status validates through the schema", () => {
  assert.ok(SetupStatusSchema.safeParse(setupStatusFromOnboarding(running)).success);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/onboarding/data/setup.test.ts`
Expected: FAIL — `setupStatusFromOnboarding`/`FAST_STEP_KINDS` not exported; old fields.

- [ ] **Step 3: Implement**

Rewrite `setup.ts` keeping `SetupApiError`, `refusalOf` and `SetupBrandKitIngestionSchema` exactly as they are, and replacing the rest:

```ts
import { z } from "zod";
// (keep the existing SetupApiError class, refusalOf(), and SetupBrandKitIngestionSchema)

/** One step of the new onboarding lane, as `GET /onboarding/current` serves it (camelCase, frozen §7). */
export const SetupStepSchema = z.object({
  kind: z.string().min(1),
  subjectRef: z.string().nullable().optional().default(null),
  phase: z.enum(["fast", "background"]).catch("background"),
  // `.catch`: an additive step status degrades to in-flight, never kills the poll (FE-N2).
  status: z.enum(["queued", "running", "completed", "empty", "failed"]).catch("running"),
  startedAt: z.string().nullable().optional().default(null),
  finishedAt: z.string().nullable().optional().default(null),
  costUsd: z.string().optional().default("0"),
  failureCode: z.string().nullable().optional().default(null),
});
export type SetupStep = z.infer<typeof SetupStepSchema>;

export const SetupStatusSchema = z.object({
  status: z.enum(["unavailable", "none", "starting", "running", "complete", "failed"]).catch("unavailable"),
  run_id: z.string().nullable().optional().default(null),
  steps: z.array(SetupStepSchema).optional().default([]),
  brand_kit_ingestion: SetupBrandKitIngestionSchema.nullable().optional().default(null),
});
export type SetupStatus = z.infer<typeof SetupStatusSchema>;

/** The steps whose completion releases the user (founder ruling 2026-09-12). */
export const FAST_STEP_KINDS = ["overview", "lineup", "reviews", "synthesis"] as const;
const STEP_DONE = new Set(["completed", "empty"]);

const OnboardingCurrentWireSchema = z.object({
  runId: z.string().nullable().optional().default(null),
  status: z.string(),
  steps: z.array(SetupStepSchema).optional().default([]),
});

/** `GET /onboarding/current` → the screen's status. Pure; the release rule lives here. */
export function setupStatusFromOnboarding(wire: unknown): SetupStatus {
  const body = OnboardingCurrentWireSchema.parse(wire);
  const fast = FAST_STEP_KINDS.map((kind) => body.steps.find((s) => s.kind === kind) ?? null);
  let status: SetupStatus["status"];
  if (body.status === "none") status = "none";
  else if (body.status === "queued") status = "starting";
  else if (body.status === "completed") status = "complete";
  else if (body.status === "failed") status = "failed";
  else if (body.status === "running") {
    if (fast.some((s) => s?.status === "failed")) status = "failed";
    else if (fast.every((s) => s !== null && STEP_DONE.has(s.status))) status = "complete";
    else status = "running";
  } else status = "unavailable";
  return SetupStatusSchema.parse({ status, run_id: body.runId, steps: body.steps, brand_kit_ingestion: null });
}

/** The profile's website as the lane wants it: a bare registrable host. */
export function companyDomainOf(companyWebsite: string): string {
  return companyWebsite.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/.*$/, "");
}

export async function startWorkspaceSetup({ companyWebsite }: { companyWebsite: string }): Promise<void> {
  const response = await fetch("/api/clue/onboarding", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ company_domain: companyDomainOf(companyWebsite), brand_id: null }),
    cache: "no-store",
  });
  if (response.ok) return;
  const refusal = await refusalOf(response, `Setup start failed with status ${response.status}`);
  // A run already open for this workspace is the replay-safe answer, not a failure.
  if (response.status === 409 && refusal.code === "onboarding_in_progress") return;
  throw refusal;
}

export async function readSetupStatus(): Promise<SetupStatus> {
  const response = await fetch("/api/clue/onboarding/current", { headers: { Accept: "application/json" }, cache: "no-store" });
  if (!response.ok) throw await refusalOf(response, `Setup status read failed with status ${response.status}`);
  return setupStatusFromOnboarding(await response.json());
}
```

Check `refusalOf`'s returned error exposes `.code` (it builds `SetupApiError(message, { status, code })` — confirm the class stores `code`). The old exports `SetupFieldStateSchema`, `SetupOfficialSiteProgressSchema`, `SetupFieldState`, `SetupOfficialSiteProgress` go; Tasks 4–5 remove their consumers.

- [ ] **Step 4: Run the data tests**

Run: `cd apps/frontend && npx tsx --test src/features/onboarding/data/setup.test.ts`
Expected: PASS. (`tsc` will fail until Tasks 4–5 land; that is expected mid-plan — commit anyway, the plan's gate is at Task 6.)

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/onboarding/data/setup.ts apps/frontend/src/features/onboarding/data/setup.test.ts
git commit -m "feat(onboarding): the setup seam calls the new onboarding lane and releases on the four fast steps"
```

---

### Task 4: Rows over steps — `setup-groups`, `setup-items`, `setup-stall`

**Files:**
- Modify: `apps/frontend/src/features/onboarding/data/setup-groups.ts`
- Modify: `apps/frontend/src/features/onboarding/model/setup-items.ts`
- Modify: `apps/frontend/src/features/onboarding/model/setup-items.test.ts`
- Modify: `apps/frontend/src/features/onboarding/model/setup-stall.ts`
- Modify: `apps/frontend/src/features/onboarding/model/setup-stall.test.ts`
- Modify: `apps/frontend/src/features/onboarding/data/onboarding.fixture.ts` (the setup rows)

**Interfaces:**
- Produces: `SETUP_GROUPS: readonly SetupGroup[]` with `{ id, label, detail, stepKinds: readonly string[] }`; `deriveSetupItems(fixtureSetup, progress: SetupStatus | null, groups = SETUP_GROUPS): SetupItem[]`; `groupStatus(steps, group, progress)`; `progressSignature(snapshot)` over `{ status, steps[{kind, subjectRef, status}] }`; `stallAdvance`, `isStalled`, `shouldStopSetupPolling` unchanged in shape.

- [ ] **Step 1: Rewrite the tests first**

`setup-items.test.ts` — replace the field-based tests with:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { onboardingFixture } from "../data/onboarding.fixture";
import { SETUP_GROUPS } from "../data/setup-groups";
import type { SetupStatus, SetupStep } from "../data/setup";
import { BRAND_KIT_ITEM_ID, FAILED_MEMBER_ANNOTATION, CONTINUING_ANNOTATION, deriveSetupItems, groupStatus } from "./setup-items";

const SETUP = onboardingFixture.setup;
function step(kind: string, status: SetupStep["status"], phase: SetupStep["phase"] = "fast", subjectRef: string | null = null): SetupStep {
  return { kind, status, phase, subjectRef, startedAt: null, finishedAt: null, costUsd: "0", failureCode: null };
}
function progress(status: SetupStatus["status"], steps: SetupStep[] = []): SetupStatus {
  return { status, run_id: "run-1", steps, brand_kit_ingestion: null };
}
const byId = (items: { id: string }[]) => Object.fromEntries(items.map((i) => [i.id, i]));

test("the row table covers the four fast kinds once, plus the persona kind on the audience row", () => {
  const kinds = SETUP_GROUPS.flatMap((g) => g.stepKinds);
  for (const kind of ["overview", "lineup", "reviews", "synthesis"]) assert.equal(kinds.filter((k) => k === kind).length, 1);
  assert.ok(SETUP_GROUPS.find((g) => g.id === "audience")?.stepKinds.includes("persona"));
});

test("before the first poll every row is queued and the brand kit row rides along", () => {
  const items = byId(deriveSetupItems(SETUP, null));
  for (const g of SETUP_GROUPS) assert.equal(items[g.id].status, "queued");
  assert.ok(items[BRAND_KIT_ITEM_ID]);
});

test("starting shows motion on the first row only", () => {
  const items = deriveSetupItems(SETUP, progress("starting"));
  assert.equal(items[0].status, "running");
  assert.ok(items.slice(1, SETUP_GROUPS.length).every((i) => i.status === "queued"));
});

test("a row runs when its step runs and completes when its fast step is completed or empty", () => {
  assert.equal(groupStatus([step("overview", "running")], SETUP_GROUPS[0], progress("running")), "running");
  assert.equal(groupStatus([step("overview", "completed")], SETUP_GROUPS[0], progress("running")), "complete");
  assert.equal(groupStatus([step("reviews", "empty")], SETUP_GROUPS[2], progress("running")), "complete");
});

test("the audience row completes on the ICP turn and says personas continue in the background", () => {
  const audience = SETUP_GROUPS.find((g) => g.id === "audience")!;
  const items = byId(deriveSetupItems(SETUP, progress("running", [step("synthesis", "completed"), step("persona", "running", "background", "clue-abm-buyers")])));
  assert.equal(items[audience.id].status, "complete");
  assert.ok(items[audience.id].detail?.endsWith(CONTINUING_ANNOTATION));
});

test("a failed fast step annotates its row and overall failed stops every spinner", () => {
  const items = byId(deriveSetupItems(SETUP, progress("failed", [step("lineup", "failed"), step("overview", "running")])));
  assert.ok(items.products.detail?.endsWith(FAILED_MEMBER_ANNOTATION));
  assert.equal(items.company.status, "queued");
});

test("overall complete forces every group complete (release consistency)", () => {
  const items = deriveSetupItems(SETUP, progress("complete", [step("overview", "running")]));
  assert.ok(items.slice(0, SETUP_GROUPS.length).every((i) => i.status === "complete"));
});
```

`setup-stall.test.ts` — keep every test, but build snapshots as `{ status, steps: [{ kind, subjectRef, status }] }` instead of `fields`/`official_site`; a new step or a step status change resets the count (replace the "new field event" and "official-site crawl movement" cases with "a new step" and "a step status change"); delete the link-expansion case.

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/frontend && npx tsx --test src/features/onboarding/model/setup-items.test.ts src/features/onboarding/model/setup-stall.test.ts`
Expected: FAIL (old shapes).

- [ ] **Step 3: Implement the rows**

`setup-groups.ts`:

```ts
/**
 * The setting-up checklist rows over the NEW onboarding lane's steps (spec 2026-09-12). DATA,
 * deliberately: the derivation (`model/setup-items.ts`) takes the table as a parameter. Labels and
 * detail lines are integration-authored copy pending founder review, as the previous table was.
 */
export interface SetupGroup {
  /** Stable across every poll tick — the frozen SetupRow keys on it. Never renumber. */
  id: string;
  label: string;
  detail: string;
  /** The step kinds this row reports. The FIRST kind decides completion; later kinds only annotate. */
  stepKinds: readonly string[];
}

export const SETUP_GROUPS: readonly SetupGroup[] = [
  { id: "company", label: "Understanding your company", detail: "Positioning, market and competitors", stepKinds: ["overview"] },
  { id: "products", label: "Your product lineup", detail: "Every offering, from your own pages", stepKinds: ["lineup", "catalog_sync"] },
  { id: "proof", label: "Customer proof", detail: "Reviews, case studies and named customers", stepKinds: ["reviews"] },
  { id: "audience", label: "ICPs and personas", detail: "Who you sell to, and who decides", stepKinds: ["synthesis", "persona"] },
];
```

`setup-items.ts` — replace the field machinery (keep `BRAND_KIT_ITEM_ID`, `brandKitItem`, `FAILED_MEMBER_ANNOTATION`, `SetupBrandKitJobSnapshot`; delete `laneItemStatus`, `SetupFieldSnapshot`, `BUDGET_STOP_ANNOTATION`, `DEEPENING_ANNOTATION`, `memberStates`, `annotationFor`, `isHalted`):

```ts
import { SETUP_GROUPS, type SetupGroup } from "../data/setup-groups";
import type { SetupStatus, SetupStep } from "../data/setup";
import type { OnboardingFlow, SetupItem } from "./onboarding";

export const BRAND_KIT_ITEM_ID = "brand-kit";
export const FAILED_MEMBER_ANNOTATION = " — part of this hit a problem";
export const CONTINUING_ANNOTATION = " — personas continue in the background";

const STEP_DONE = new Set<SetupStep["status"]>(["completed", "empty"]);
const HALTED_OVERALL = new Set(["failed", "unavailable"]);

/** The one step this row completes on (its first kind), or null before the lane reaches it. */
function leadStep(steps: readonly SetupStep[], group: SetupGroup): SetupStep | null {
  return steps.find((s) => s.kind === group.stepKinds[0]) ?? null;
}

export function groupStatus(steps: readonly SetupStep[], group: SetupGroup, progress: Pick<SetupStatus, "status">): SetupItem["status"] {
  if (progress.status === "complete") return "complete";
  const lead = leadStep(steps, group);
  if (lead === null) return "queued";
  if (STEP_DONE.has(lead.status)) return "complete";
  if (lead.status === "running" && !HALTED_OVERALL.has(progress.status)) return "running";
  return "queued";
}

function annotationFor(steps: readonly SetupStep[], group: SetupGroup): string {
  const mine = steps.filter((s) => group.stepKinds.includes(s.kind));
  if (mine.some((s) => s.status === "failed")) return FAILED_MEMBER_ANNOTATION;
  const lead = leadStep(steps, group);
  const trailing = mine.filter((s) => s.kind !== group.stepKinds[0]);
  if (lead && STEP_DONE.has(lead.status) && trailing.some((s) => s.status === "running" || s.status === "queued")) {
    return group.id === "audience" ? CONTINUING_ANNOTATION : "";
  }
  return "";
}

// keep brandKitItem(row, job) exactly as it is

export function deriveSetupItems(
  fixtureSetup: OnboardingFlow["setup"],
  progress: SetupStatus | null,
  groups: readonly SetupGroup[] = SETUP_GROUPS,
): SetupItem[] {
  const steps = progress?.steps ?? [];
  const warmingUp = progress?.status === "starting" && steps.length === 0;
  const items: SetupItem[] = groups.map((group, index) => {
    const status = groupStatus(steps, group, progress ?? { status: "" });
    const annotation = progress === null ? "" : annotationFor(steps, group);
    return {
      id: group.id,
      label: group.label,
      detail: `${group.detail}${annotation}`,
      status: warmingUp && index === 0 && status === "queued" ? "running" : status,
    };
  });
  const brandKit = fixtureSetup.items.find((item) => item.id === BRAND_KIT_ITEM_ID);
  if (brandKit) items.push(brandKitItem(brandKit, progress?.brand_kit_ingestion ?? null));
  return items;
}
```

`setup-stall.ts` — replace `SetupStallSnapshot` and `progressSignature`:

```ts
export interface SetupStallSnapshot {
  status: string;
  steps?: readonly { kind: string; subjectRef?: string | null; status: string }[];
}

export function progressSignature(snapshot: SetupStallSnapshot): string {
  return JSON.stringify([
    snapshot.status,
    (snapshot.steps ?? []).map((s) => [s.kind, s.subjectRef ?? null, s.status]),
  ]);
}
```

Keep `stallAdvance`, `isStalled`, `shouldStopSetupPolling` as they are (they compare signatures and statuses only; confirm `IN_FLIGHT` still names `starting`/`running`).

`onboarding.fixture.ts` — the `setup.items` array becomes five rows with the ids above plus `brand-kit`: `company`, `products`, `proof`, `audience` (labels/details from `SETUP_GROUPS`) and the existing `brand-kit` row unchanged. The fixture's role is the rows' identities; its statuses are the preview's initial state.

- [ ] **Step 4: Run the model tests**

Run: `cd apps/frontend && npx tsx --test src/features/onboarding/model/setup-items.test.ts src/features/onboarding/model/setup-stall.test.ts src/features/onboarding/model/onboarding.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/onboarding/data/setup-groups.ts apps/frontend/src/features/onboarding/model/setup-items.ts apps/frontend/src/features/onboarding/model/setup-items.test.ts apps/frontend/src/features/onboarding/model/setup-stall.ts apps/frontend/src/features/onboarding/model/setup-stall.test.ts apps/frontend/src/features/onboarding/data/onboarding.fixture.ts
git commit -m "feat(onboarding): checklist rows derive from the new lane's steps; the audience row says personas continue"
```

---

### Task 5: The fixture stream, the hook's start input, the screen

**Files:**
- Modify: `apps/frontend/src/features/onboarding/data/setup-progress.fixture.ts`
- Modify: `apps/frontend/src/features/onboarding/data/setup-progress.repository.ts` (types only if needed)
- Modify: `apps/frontend/src/features/onboarding/data/setup-progress.repository.test.ts`
- Modify: `apps/frontend/src/features/onboarding/hooks/use-setup-progress.ts` (`ensureStarted` passes the website)
- Modify: `apps/frontend/src/features/onboarding/components/live-setup-screen.tsx` (passes the website into the hook)

**Interfaces:**
- Consumes: `SetupProgressSource.start()` becomes `start(input: { companyWebsite: string })`.
- Produces: `useSetupProgress(input: { companyWebsite: string }, source = httpSetupProgressSource)`; `LiveSetupScreen` reads the website from `flow.account.companyWebsite` (the profile step wrote it — `OnboardingFlowSchema.account.companyWebsite`), passing it down.

- [ ] **Step 1: Rewrite the fixture stream** as new-shape frames (replace `FIXTURE_SETUP_ONBOARDING_FIELDS`, `FIXTURE_OFFICIAL_SITE_PROGRESS` and the script):

```ts
import { SetupStatusSchema, type SetupStatus, type SetupStep } from "./setup";

function step(kind: string, status: SetupStep["status"], phase: SetupStep["phase"] = "fast", subjectRef: string | null = null): SetupStep {
  return { kind, status, phase, subjectRef, startedAt: null, finishedAt: null, costUsd: "0", failureCode: null };
}
const frame = (status: SetupStatus["status"], steps: SetupStep[]): SetupStatus =>
  SetupStatusSchema.parse({ status, run_id: "run-fixture", steps, brand_kit_ingestion: null });

/**
 * A scripted new-lane run: queued → the three fast reads in parallel → the ICP turn → release,
 * with personas and per-product research continuing in the background after the release frame.
 */
export const FIXTURE_SETUP_PROGRESS_SCRIPT: readonly SetupStatus[] = [
  frame("starting", []),
  frame("running", [step("overview", "running"), step("lineup", "running"), step("reviews", "running")]),
  frame("running", [step("overview", "completed"), step("lineup", "completed"), step("catalog_sync", "completed"), step("reviews", "empty"), step("synthesis", "running")]),
  frame("complete", [step("overview", "completed"), step("lineup", "completed"), step("catalog_sync", "completed"), step("reviews", "empty"), step("synthesis", "completed"), step("persona", "running", "background", "clue-abm-buyers"), step("product_research", "queued", "background", "prd-1")]),
];
```

Update `setup-progress.repository.test.ts` to walk this script through `createFixtureSetupProgressSource` and assert: frame 1 renders the first row running and the rest queued; frame 3 renders company/products/proof complete and audience running; frame 4 is `complete` and the audience row carries `CONTINUING_ANNOTATION`; the stream sticks on the last frame. Remove imports of the deleted exports.

- [ ] **Step 2: The hook and the screen**

In `use-setup-progress.ts`: signature `useSetupProgress({ companyWebsite }: { companyWebsite: string }, source: SetupProgressSource = httpSetupProgressSource)`; in `ensureStarted` call `await sourceRef.current.start({ companyWebsite })`. The `[]` effect deps stay (the website is fixed for the screen's life; capture it in a ref like `sourceRef`). Everything else in the hook is unchanged: release on `complete`, the two stall budgets, the terminals.

In `setup-progress.repository.ts`: `start(input: { companyWebsite: string }): Promise<void>` on the interface; `httpSetupProgressSource.start = startWorkspaceSetup`; the fixture source's `start` ignores its argument.

In `live-setup-screen.tsx`: accept `companyWebsite: string` alongside `setup`, and call `useSetupProgress({ companyWebsite })`. In `onboarding-screen.tsx` pass `companyWebsite={flow.account.companyWebsite}` (check where the profile draft lands in `flow`/controller state — `use-onboarding-controller.ts:165` posts `company_website` from `draft.companyWebsite`; read the same value the provisioning call used, exposed by the controller, and pass it; if the controller does not expose the draft after provisioning, expose `companyWebsite` from it).

- [ ] **Step 3: Run tests, lint, tsc**

Run: `cd apps/frontend && npm test 2>&1 | grep -E "^ℹ (tests|pass|fail)" && npm run lint && npx tsc --noEmit -p . 2>&1 | grep -c "error TS"`
Expected: pass; lint 0 errors; tsc back at the baseline (every consumer of the removed exports is gone — search `SetupFieldStateSchema|SetupOfficialSiteProgress|FIXTURE_SETUP_ONBOARDING_FIELDS|FIXTURE_OFFICIAL_SITE_PROGRESS|laneItemStatus|BUDGET_STOP_ANNOTATION|DEEPENING_ANNOTATION` under `src/` and expect zero hits).

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/features/onboarding
git commit -m "feat(onboarding): the setting-up screen starts and follows the new onboarding lane; fixture stream in the new shape"
```

---

### Task 6: Source contract, build, docs, memory

**Files:**
- Create: `apps/frontend/src/features/onboarding/model/onboarding-lane-contract.test.ts`
- Create or modify: `apps/frontend/docs/api-contracts/onboarding.md`
- Modify: `docs/superpowers/plans/2026-09-11-arv2-defect-and-remaining-work-ledger.md` (A3, A4, A5 → fixed)
- Modify: `_memory/2026-09-11-san-salvador-lane-stack.md`

- [ ] **Step 1: The source-contract test**

```ts
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}

test("the setting-up screen names only the new onboarding lane", () => {
  const root = new URL("../", import.meta.url);
  const offenders: string[] = [];
  const walk = (dir: URL) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const child = new URL(entry.name + (entry.isDirectory() ? "/" : ""), dir);
      if (entry.isDirectory()) walk(child);
      else if (/\.(ts|tsx)$/.test(entry.name) && /stage0\/setup/.test(readFileSync(child, "utf8"))) offenders.push(child.pathname);
    }
  };
  walk(root);
  assert.deepEqual(offenders, []);
  assert.match(source("../data/setup.ts"), /\/api\/clue\/onboarding\/current/);
  assert.match(source("../data/setup.ts"), /FAST_STEP_KINDS = \["overview", "lineup", "reviews", "synthesis"\]/);
  assert.match(source("../hooks/use-setup-progress.ts"), /window\.location\.replace\("\/session\/establish"\)/);
});
```

- [ ] **Step 2: Run the whole frontend gate**

Run: `cd apps/frontend && npm test 2>&1 | grep -E "^ℹ (tests|pass|fail)" && npm run lint && npx tsc --noEmit -p . 2>&1 | grep -c "error TS" && npm run build 2>&1 | tail -3`
Expected: pass; 0 lint errors; tsc baseline; build green.

- [ ] **Step 3: Docs**

`apps/frontend/docs/api-contracts/onboarding.md` — append (create with a `# Onboarding API contract` heading if absent):

```markdown
## The setting-up screen runs the new onboarding lane (2026-09-12)

Spec `docs/superpowers/specs/archive/2026-09-12-onboarding-v2-default-design.md`. After provisioning, the
setting-up screen posts `POST /api/clue/onboarding` `{ company_domain, brand_id: null }` (the
profile's website, folded to its host; a 409 `onboarding_in_progress` is the replay-safe answer)
and polls `GET /api/clue/onboarding/current` every 1.5 s. The screen's `SetupStatus` is derived in
`data/setup.ts`: `complete` when every fast step (`overview`, `lineup`, `reviews`, `synthesis`) is
`completed` or `empty`, `failed` when one is `failed`, `starting` for a queued run, `none` before
the first post. Rows (`data/setup-groups.ts`) map onto step kinds: company, products, proof,
audience (which completes on the ICP turn and notes that personas continue in the background),
plus the brand-kit row over the ingestion job. Release, stall and error handling are unchanged.
Backend: `CLUE_ONBOARDING_V2_ENABLED` defaults on; the old Stage-0 recon composes only behind
`CLUE_LEGACY_STAGE0_RECON_ENABLED` (default off) until section G of the ledger retires it.
```

Ledger: mark A3, A4 and A5 `**fixed** (2026-09-12, plan onboarding-v2-default)` in their Status cells, naming the commits.

Memory note — append:

```markdown

## Onboarding v2 is the default (plan 2026-09-12-onboarding-v2-default)

`CLUE_ONBOARDING_V2_ENABLED=true` by default; `CLUE_LEGACY_STAGE0_RECON_ENABLED=false` gates the
old recon (binder, `/stage0/setup`, STAGE0_RECON handler). The setting-up screen posts
`/api/clue/onboarding` and polls `/api/clue/onboarding/current`; release on the four fast steps.
Ledger A3/A4/A5 closed. Owed: a fresh-workspace walk (sign up → profile → setting-up fills from
the new lane → released → Brand context shows the documents, personas landing after).
```

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/features/onboarding/model/onboarding-lane-contract.test.ts apps/frontend/docs/api-contracts/onboarding.md docs/superpowers/plans/2026-09-11-arv2-defect-and-remaining-work-ledger.md _memory/2026-09-11-san-salvador-lane-stack.md
git commit -m "docs: the new onboarding lane is the Welcome flow's pipeline — contract note, ledger A3/A4/A5 closed, memory"
```

---

## Self-review

- **Spec coverage.** §2 data seam: Task 3 (both calls, the derivation, 409 replay, the proxy needs no route). §3 rows: Task 4 (four rows over kinds + brand kit; audience annotation). §4 release/stall: Task 5 keeps the hook's lifecycle; the stall signature now reads steps. §5 backend: Tasks 1–2. §6 tests: each task; Task 6's contract test pins "no `stage0/setup` in the feature". §7: old endpoints untouched, no visual change.
- **Placeholder scan.** Task 5 tells the implementer where the website value comes from and what to do if the controller does not expose it; Task 2 tells them to read one test before deciding a flag. No "TBD".
- **Type consistency.** `SetupStatus` = `{ status, run_id, steps, brand_kit_ingestion }` everywhere (Tasks 3–5); `SetupGroup.stepKinds` (Task 4) is what `groupStatus`/`annotationFor` read; `start({ companyWebsite })` matches Tasks 3 and 5; `FAST_STEP_KINDS` spelled identically in Tasks 3 and 6.
