import assert from "node:assert/strict";
import test from "node:test";
import { onboardingFixture } from "../data/onboarding.fixture";
import { SETUP_GROUPS, type SetupGroup } from "../data/setup-groups";
import type { SetupStatus, SetupStep } from "../data/setup";
import {
  BRAND_KIT_ITEM_ID,
  CONTINUING_ANNOTATION,
  FAILED_MEMBER_ANNOTATION,
  deriveSetupItems,
  groupStatus,
  type SetupBrandKitJobSnapshot,
} from "./setup-items";

const SETUP = onboardingFixture.setup;

function step(
  kind: string,
  status: SetupStep["status"],
  phase: SetupStep["phase"] = "fast",
  subjectRef: string | null = null,
): SetupStep {
  return { kind, status, phase, subjectRef, startedAt: null, finishedAt: null, costUsd: "0", failureCode: null };
}

function progress(status: SetupStatus["status"], steps: SetupStep[] = []): SetupStatus {
  return { status, run_id: "run-1", steps, brand_kit_ingestion: null };
}

const byId = <T extends { id: string }>(items: T[]): Record<string, T> =>
  Object.fromEntries(items.map((i) => [i.id, i]));

test("the row table covers the four fast kinds once, plus the persona kind on the audience row", () => {
  const kinds = SETUP_GROUPS.flatMap((g) => g.stepKinds);
  for (const kind of ["overview", "lineup", "reviews", "synthesis"]) {
    assert.equal(kinds.filter((k) => k === kind).length, 1);
  }
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

test("a running run with no step yet warms up too, not a checklist of dead rows", () => {
  // Between `mark_run_running` and the first `start_step` the run reports `running` with zero
  // steps. Every row queued with nothing spinning would read as a lane that had stalled.
  const items = deriveSetupItems(SETUP, progress("running"));
  assert.equal(items[0].status, "running");
  assert.ok(items.slice(1, SETUP_GROUPS.length).every((i) => i.status === "queued"));
  // The first real step supersedes the placeholder — the warm-up never outlives step truth.
  const stepped = deriveSetupItems(SETUP, progress("running", [step("lineup", "running")]));
  assert.equal(stepped[0].status, "queued");
});

test("a row runs when its step runs and completes when its fast step is completed or empty", () => {
  assert.equal(groupStatus([step("overview", "running")], SETUP_GROUPS[0], progress("running")), "running");
  assert.equal(groupStatus([step("overview", "completed")], SETUP_GROUPS[0], progress("running")), "complete");
  // `empty` is a CORRECT outcome — nobody found reviews to cite — not a failure.
  assert.equal(groupStatus([step("reviews", "empty")], SETUP_GROUPS[2], progress("running")), "complete");
});

test("a step of another row never moves this one", () => {
  assert.equal(groupStatus([step("lineup", "running")], SETUP_GROUPS[0], progress("running")), "queued");
});

test("the continuing note is table truth, and it is not empty", () => {
  // `CONTINUING_ANNOTATION` is sourced from `SetupGroup.continuingNote`, so a row that lost its
  // note would silently turn every `endsWith(CONTINUING_ANNOTATION)` assertion into a tautology.
  assert.notEqual(CONTINUING_ANNOTATION, "");
  assert.equal(SETUP_GROUPS.find((g) => g.id === "audience")?.continuingNote, CONTINUING_ANNOTATION);
  assert.ok(SETUP_GROUPS.filter((g) => g.continuingNote !== undefined).length === 1);
});

test("the audience row completes on the ICP turn and says personas continue in the background", () => {
  const audience = SETUP_GROUPS.find((g) => g.id === "audience")!;
  const items = byId(
    deriveSetupItems(
      SETUP,
      progress("running", [
        step("synthesis", "completed"),
        step("persona", "running", "background", "clue-abm-buyers"),
      ]),
    ),
  );
  assert.equal(items[audience.id].status, "complete");
  assert.ok(items[audience.id].detail?.endsWith(CONTINUING_ANNOTATION));
});

test("the promise is made on the release tick, before a persona step exists", () => {
  // Persona steps are created AFTER `synthesis` completes — usually the very tick that releases
  // the user. Waiting for one to appear means the promise is never rendered at all.
  const items = byId(deriveSetupItems(SETUP, progress("running", [step("synthesis", "completed")])));
  assert.equal(items.audience.status, "complete");
  assert.ok(items.audience.detail?.endsWith(CONTINUING_ANNOTATION));
  // …and it disappears once the persona work has actually finished.
  const done = byId(
    deriveSetupItems(
      SETUP,
      progress("running", [
        step("synthesis", "completed"),
        step("persona", "completed", "background", "clue-abm-buyers"),
      ]),
    ),
  );
  assert.ok(!done.audience.detail?.includes(CONTINUING_ANNOTATION));
  // A row with no continuing note never claims one.
  assert.ok(!items.company.detail?.includes(CONTINUING_ANNOTATION));
});

test("a failed fast step annotates its row and overall failed stops every spinner", () => {
  const items = byId(
    deriveSetupItems(SETUP, progress("failed", [step("lineup", "failed"), step("overview", "running")])),
  );
  assert.ok(items.products.detail?.endsWith(FAILED_MEMBER_ANNOTATION));
  assert.equal(items.company.status, "queued");
});

test("overall complete forces every group complete (release consistency)", () => {
  const items = deriveSetupItems(SETUP, progress("complete", [step("overview", "running")]));
  assert.ok(items.slice(0, SETUP_GROUPS.length).every((i) => i.status === "complete"));
});

test("row ids are stable across ticks so the live region never re-keys its rows", () => {
  const ticks = [
    deriveSetupItems(SETUP, null),
    deriveSetupItems(SETUP, progress("starting")),
    deriveSetupItems(SETUP, progress("running", [step("overview", "running")])),
    deriveSetupItems(SETUP, progress("complete", [step("overview", "completed")])),
  ];
  const ids = ticks.map((items) => items.map((item) => item.id).join(","));
  assert.equal(new Set(ids).size, 1);
});

/** The brand-kit row after a derivation, or `undefined` when the fixture dropped it. */
function brandKitRow(status: SetupStatus | null) {
  return deriveSetupItems(SETUP, status).find((item) => item.id === BRAND_KIT_ITEM_ID);
}

/** A tick carrying an ingestion job. The job status is structurally typed (`SetupBrandKitJobSnapshot`)
 * so the unrecognized-status case below is expressible; the schema's `.catch` is its real defence. */
function withJob(job: SetupBrandKitJobSnapshot | null, status: SetupStatus["status"] = "running"): SetupStatus {
  return { ...progress(status), brand_kit_ingestion: job as SetupStatus["brand_kit_ingestion"] };
}

/** The fixture's own brand-kit detail line — the base every mapping keeps. */
const BRAND_KIT_DETAIL = SETUP.items.find((item) => item.id === BRAND_KIT_ITEM_ID)?.detail;

test("no ingestion job leaves the brand-kit row queued, and the fixture status never leaks", () => {
  // The fixture claims `running` for the design-review theatre; live truth is the only input.
  assert.equal(SETUP.items.find((item) => item.id === BRAND_KIT_ITEM_ID)?.status, "running");
  assert.equal(brandKitRow(null)?.status, "queued");
  assert.equal(brandKitRow(progress("complete"))?.status, "queued");
  assert.equal(brandKitRow(withJob(null))?.status, "queued");
  assert.equal(brandKitRow(withJob(null))?.detail, BRAND_KIT_DETAIL);
});

test("a queued or running ingestion job runs the brand-kit row", () => {
  for (const status of ["queued", "running"]) {
    const row = brandKitRow(withJob({ job_id: "ingest_1", status }));
    assert.equal(row?.status, "running", `job ${status} must read as running`);
    assert.equal(row?.detail, BRAND_KIT_DETAIL);
  }
});

test("a succeeded ingestion job completes the brand-kit row", () => {
  const row = brandKitRow(withJob({ job_id: "ingest_1", status: "succeeded" }));
  assert.equal(row?.status, "complete");
  assert.equal(row?.detail, BRAND_KIT_DETAIL);
});

test("a failed ingestion job annotates instead of claiming a kit exists", () => {
  // The row vocabulary has no failed state: `complete` would claim a kit nothing produced, so
  // the failure rides the detail line — the same idiom a failed step uses on its own row.
  const row = brandKitRow(withJob({ job_id: "ingest_1", status: "failed" }, "complete"));
  assert.equal(row?.status, "queued");
  assert.equal(row?.detail, `${BRAND_KIT_DETAIL}${FAILED_MEMBER_ANNOTATION}`);
});

test("an unrecognized job status reads as in-flight, never as a kit that exists", () => {
  const row = brandKitRow(withJob({ job_id: "ingest_1", status: "some-future-status" }));
  assert.equal(row?.status, "running");
  assert.equal(row?.detail, BRAND_KIT_DETAIL);
});

test("the brand-kit row is independent of the step rows it sits under", () => {
  // The warm-up rule is index-0-only and the group reduction never sees the job: a released,
  // fully-complete run with a still-running ingestion keeps the two truths separate.
  const items = deriveSetupItems(SETUP, withJob({ job_id: "ingest_1", status: "running" }, "complete"));
  assert.deepEqual(
    items.map((item) => item.status),
    ["complete", "complete", "complete", "complete", "running"],
  );
  // …and a halted run does not demote a kit that genuinely published.
  const halted = deriveSetupItems(SETUP, withJob({ job_id: "ingest_1", status: "succeeded" }, "failed"));
  assert.deepEqual(
    halted.map((item) => item.status),
    ["queued", "queued", "queued", "queued", "complete"],
  );
  // The warm-up row stays the first GROUP even when the brand kit is the only thing moving.
  const warming = deriveSetupItems(SETUP, withJob({ job_id: "ingest_1", status: "queued" }, "starting"));
  assert.equal(warming[0]?.id, SETUP_GROUPS[0]?.id);
  assert.equal(warming[0]?.status, "running");
});

test("a fixture without the brand-kit row drops it cleanly", () => {
  const withoutBrandKit = {
    ...SETUP,
    items: SETUP.items.filter((item) => item.id !== BRAND_KIT_ITEM_ID),
  };
  const items = deriveSetupItems(withoutBrandKit, null);
  assert.equal(items.length, SETUP_GROUPS.length);
});

test("the group table is a parameter, not a hard-wired dependency", () => {
  const table: readonly SetupGroup[] = [
    { id: "solo", label: "Solo", detail: "One step", stepKinds: ["overview"] },
  ];
  const items = deriveSetupItems(SETUP, progress("running", [step("overview", "completed")]), table);
  assert.equal(items.length, 2);
  assert.equal(items[0]?.id, "solo");
  assert.equal(items[0]?.status, "complete");
});

test("a halted run never spins the brand-kit row; finished outcomes still show", () => {
  // First production onboarding (2026-10-03): company research failed while the website ingestion
  // was still running, polling stopped (a halted run surfaces recovery controls), and the row kept
  // spinning on its last-seen `running` forever — after the job had in fact succeeded. Once the run
  // has halted, that `running` is stale, exactly as for the step rows (`groupStatus`).
  for (const halted of ["failed", "unavailable"] as const) {
    for (const status of ["queued", "running", "some-future-status"]) {
      const row = brandKitRow(withJob({ job_id: "ingest_1", status }, halted));
      assert.equal(row?.status, "queued", `job ${status} under a ${halted} run must not spin`);
      assert.equal(row?.detail, BRAND_KIT_DETAIL);
    }
    assert.equal(brandKitRow(withJob({ job_id: "ingest_1", status: "succeeded" }, halted))?.status, "complete");
    const failed = brandKitRow(withJob({ job_id: "ingest_1", status: "failed" }, halted));
    assert.equal(failed?.detail, `${BRAND_KIT_DETAIL}${FAILED_MEMBER_ANNOTATION}`);
  }
});

test("an ingestion job that finished with gaps still completes the brand-kit row", () => {
  // The kit was published; what it lacks (failed descriptions, no ad card) is a repair's job.
  const row = brandKitRow(withJob({ job_id: "ingest_1", status: "succeeded_with_gaps" }));
  assert.equal(row?.status, "complete");
  assert.equal(row?.detail, BRAND_KIT_DETAIL);
});
