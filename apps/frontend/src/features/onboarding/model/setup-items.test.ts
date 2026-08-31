import assert from "node:assert/strict";
import test from "node:test";
import { onboardingFixture } from "../data/onboarding.fixture";
import { SETUP_GROUPS, type SetupGroup } from "../data/setup-groups";
import {
  BRAND_KIT_ITEM_ID,
  BUDGET_STOP_ANNOTATION,
  DEEPENING_ANNOTATION,
  FAILED_MEMBER_ANNOTATION,
  deriveSetupItems,
  groupStatus,
  laneItemStatus,
  type SetupFieldSnapshot,
} from "./setup-items";

const SETUP = onboardingFixture.setup;

function field(
  field_key: string,
  status: SetupFieldSnapshot["status"],
  lane: SetupFieldSnapshot["lane"] = "fast",
): SetupFieldSnapshot {
  return { field_key, lane, status };
}

/** The ratified group-1 members, so the tests read against the table rather than restate it. */
const GROUP_1 = SETUP_GROUPS[0] as SetupGroup;
const GROUP_2 = SETUP_GROUPS[1] as SetupGroup;

test("laneItemStatus covers every real recon lane status explicitly", () => {
  assert.equal(laneItemStatus("queued"), "queued");
  assert.equal(laneItemStatus("running"), "running");
  assert.equal(laneItemStatus("completed"), "complete");
  // failed/paused must NOT read as queued — that would assert "this will happen".
  assert.equal(laneItemStatus("failed"), "stopped");
  assert.equal(laneItemStatus("paused"), "stopped");
  assert.equal(laneItemStatus(null), "queued");
});

test("the ratified table partitions the eleven onboarding fields, once each", () => {
  const keys = SETUP_GROUPS.flatMap((group) => [...group.fieldKeys]);
  assert.equal(keys.length, 11);
  assert.equal(new Set(keys).size, 11);
  assert.equal(keys.includes("client.product_catalog"), false);
  assert.equal(SETUP_GROUPS.length, 4);
});

test("pre-first-poll derivation renders four queued groups plus the dummy brand kit", () => {
  const items = deriveSetupItems(SETUP, null);
  assert.equal(items.length, 5);
  assert.deepEqual(
    items.map((item) => item.status),
    ["queued", "queued", "queued", "queued", "queued"],
  );
  assert.deepEqual(
    items.slice(0, 4).map((item) => item.id),
    SETUP_GROUPS.map((group) => group.id),
  );
  const brandKit = items.find((item) => item.id === BRAND_KIT_ITEM_ID);
  assert.ok(brandKit);
  assert.equal(brandKit.label, "Creating brand kit");
});

test("starting shows motion on the first group only while no field event exists yet", () => {
  const items = deriveSetupItems(SETUP, { status: "starting" });
  assert.deepEqual(
    items.map((item) => item.status),
    ["running", "queued", "queued", "queued", "queued"],
  );
  // No fabricated detail: the motion rule never annotates.
  assert.equal(items[0]?.detail, SETUP_GROUPS[0]?.detail);
});

test("the first real field event supersedes the starting motion rule", () => {
  const items = deriveSetupItems(SETUP, {
    status: "starting",
    fields: [field(GROUP_2.fieldKeys[0]!, "started")],
  });
  // Group 1 has no event of its own: event truth wins over the warm-up placeholder.
  assert.equal(items[0]?.status, "queued");
  assert.equal(items[1]?.status, "running");
});

test("a group runs on its first member event and completes only when every member is terminal", () => {
  const partial = deriveSetupItems(SETUP, {
    status: "running",
    fields: [field(GROUP_1.fieldKeys[0]!, "resolved")],
  });
  assert.equal(partial[0]?.status, "running");

  const done = deriveSetupItems(SETUP, {
    status: "running",
    fields: [
      field(GROUP_1.fieldKeys[0]!, "resolved"),
      // `empty` and `failed` are terminal too: an unanswerable field is a correct outcome,
      // and a failed one is finished work, not pending work.
      field(GROUP_1.fieldKeys[1]!, "empty"),
      field(GROUP_1.fieldKeys[2]!, "failed"),
    ],
  });
  assert.equal(done[0]?.status, "complete");
});

test("an in-flight member keeps the group running even when its siblings are terminal", () => {
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fields: [
      field(GROUP_1.fieldKeys[0]!, "resolved"),
      field(GROUP_1.fieldKeys[1]!, "resolved"),
      field(GROUP_1.fieldKeys[2]!, "started"),
    ],
  });
  assert.equal(items[0]?.status, "running");
});

test("overall complete forces every group complete (release consistency)", () => {
  const items = deriveSetupItems(SETUP, {
    status: "complete",
    fields: [field(GROUP_1.fieldKeys[0]!, "started")],
  });
  assert.deepEqual(
    items.slice(0, 4).map((item) => item.status),
    ["complete", "complete", "complete", "complete"],
  );
});

test("a halted run never leaves a spinner running on work nothing is doing", () => {
  const fields = [
    field(GROUP_1.fieldKeys[0]!, "resolved"),
    field(GROUP_1.fieldKeys[1]!, "failed"),
    // GROUP_1.fieldKeys[2] and every later group were never reached.
  ];
  for (const status of ["failed", "unavailable"]) {
    const items = deriveSetupItems(SETUP, { status, fields });
    assert.deepEqual(
      items.map((item) => item.status),
      ["queued", "queued", "queued", "queued", "queued"],
      `${status} must not fabricate motion`,
    );
    // The truth of what happened stays on the detail line (plus the screen's failure block).
    assert.equal(items[0]?.detail, `${GROUP_1.detail}${FAILED_MEMBER_ANNOTATION}`);
  }
});

test("a halted run still credits a group that genuinely finished", () => {
  const items = deriveSetupItems(SETUP, {
    status: "failed",
    fields: GROUP_2.fieldKeys.map((key) => field(key, "resolved")),
  });
  assert.equal(items[1]?.status, "complete");
});

test("a PAUSED fast lane stops the spinner even though overall status still reads running", () => {
  // The backend maps every non-failed, non-completed fast lane to overall "running"
  // (stage0_setup.py), so lane truth is the only place a pause is visible.
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fast_status: "paused",
    background_status: "queued",
    fields: [field(GROUP_1.fieldKeys[0]!, "resolved")],
  });
  assert.equal(items[0]?.status, "queued");
  assert.equal(items[1]?.status, "queued");
});

test("a paused fast lane the background lane picked up is real motion, not a halt", () => {
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fast_status: "paused",
    background_status: "running",
    fields: [field(GROUP_1.fieldKeys[0]!, "resolved")],
  });
  assert.equal(items[0]?.status, "running");
});

test("a running fast lane is motion regardless of a stopped background lane", () => {
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fast_status: "running",
    background_status: "paused",
    fields: [field(GROUP_1.fieldKeys[0]!, "resolved")],
  });
  assert.equal(items[0]?.status, "running");
});

test("a stopped background lane cannot un-complete a released run", () => {
  const items = deriveSetupItems(SETUP, {
    status: "complete",
    fast_status: "completed",
    background_status: "failed",
    fields: [field(GROUP_1.fieldKeys[0]!, "started", "background")],
  });
  assert.deepEqual(
    items.slice(0, 4).map((item) => item.status),
    ["complete", "complete", "complete", "complete"],
  );
});

test("a failed member is annotated on the detail line, never as a new visual state", () => {
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fields: [field(GROUP_2.fieldKeys[0]!, "failed")],
  });
  assert.equal(items[1]?.detail, `${GROUP_2.detail}${FAILED_MEMBER_ANNOTATION}`);
  // The frozen three-state vocabulary is untouched.
  assert.ok(["complete", "running", "queued"].includes(items[1]?.status ?? ""));
});

test("a budget-stopped lane annotates every group holding an unreached member", () => {
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fast_budget_exhausted: true,
    fields: [field(GROUP_1.fieldKeys[0]!, "resolved")],
  });
  // Group 1 still has unreached members, group 2 was never started at all.
  assert.equal(items[0]?.detail, `${GROUP_1.detail}${BUDGET_STOP_ANNOTATION}`);
  assert.equal(items[1]?.detail, `${GROUP_2.detail}${BUDGET_STOP_ANNOTATION}`);
});

test("a released run still admits the members its budget never reached", () => {
  // The pairing a user actually sees: the fast lane completed (release), but it stopped at the
  // cap first, so "complete" must not be allowed to imply full coverage.
  const items = deriveSetupItems(SETUP, {
    status: "complete",
    fast_status: "completed",
    fast_budget_exhausted: true,
    fields: [field(GROUP_1.fieldKeys[0]!, "resolved")],
  });
  assert.equal(items[0]?.status, "complete");
  assert.equal(items[0]?.detail, `${GROUP_1.detail}${BUDGET_STOP_ANNOTATION}`);
});

test("the background lane's own budget verdict annotates on its own", () => {
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fast_budget_exhausted: false,
    background_budget_exhausted: true,
    fields: [field(GROUP_1.fieldKeys[0]!, "resolved")],
  });
  assert.equal(items[0]?.detail, `${GROUP_1.detail}${BUDGET_STOP_ANNOTATION}`);
});

test("an unknown budget verdict never fabricates a budget claim", () => {
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fast_budget_exhausted: null,
    background_budget_exhausted: null,
    fields: [field(GROUP_1.fieldKeys[0]!, "resolved")],
  });
  assert.equal(items[0]?.detail, GROUP_1.detail);
  assert.equal(items[1]?.detail, GROUP_2.detail);
});

test("a background re-run of an already-covered group reads as deepening, not a bare restart", () => {
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fields: [
      field(GROUP_1.fieldKeys[0]!, "started", "background"),
      field(GROUP_1.fieldKeys[1]!, "resolved"),
      field(GROUP_1.fieldKeys[2]!, "resolved"),
    ],
  });
  assert.equal(items[0]?.status, "running");
  assert.equal(items[0]?.detail, `${GROUP_1.detail}${DEEPENING_ANNOTATION}`);
});

test("deepening also explains a completed group the background lane is revisiting", () => {
  const items = deriveSetupItems(SETUP, {
    status: "complete",
    fields: [
      field(GROUP_1.fieldKeys[0]!, "started", "background"),
      field(GROUP_1.fieldKeys[1]!, "resolved"),
      field(GROUP_1.fieldKeys[2]!, "resolved"),
    ],
  });
  assert.equal(items[0]?.status, "complete");
  assert.equal(items[0]?.detail, `${GROUP_1.detail}${DEEPENING_ANNOTATION}`);
});

test("a budget-stopped fast lane never lets background work be called deepening", () => {
  // With the fast lane cut off at the cap, a background `started` may be FIRST contact with
  // that field, not a second pass — so the deepening claim is withheld.
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fast_budget_exhausted: true,
    fields: [
      field(GROUP_1.fieldKeys[0]!, "started", "background"),
      field(GROUP_1.fieldKeys[1]!, "resolved"),
      field(GROUP_1.fieldKeys[2]!, "resolved"),
    ],
  });
  assert.equal(items[0]?.detail, GROUP_1.detail);
});

test("a first-pass fast-lane group is never called deepening", () => {
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fields: [
      field(GROUP_1.fieldKeys[0]!, "started"),
      field(GROUP_1.fieldKeys[1]!, "resolved"),
      field(GROUP_1.fieldKeys[2]!, "resolved"),
    ],
  });
  assert.equal(items[0]?.detail, GROUP_1.detail);
});

test("a failed member outranks the budget and deepening annotations (one clause only)", () => {
  const items = deriveSetupItems(SETUP, {
    status: "running",
    fast_budget_exhausted: true,
    fields: [
      field(GROUP_1.fieldKeys[0]!, "failed"),
      field(GROUP_1.fieldKeys[1]!, "started", "background"),
    ],
  });
  assert.equal(items[0]?.detail, `${GROUP_1.detail}${FAILED_MEMBER_ANNOTATION}`);
});

test("row ids are stable across ticks so the live region never re-keys its rows", () => {
  const ticks = [
    deriveSetupItems(SETUP, null),
    deriveSetupItems(SETUP, { status: "starting" }),
    deriveSetupItems(SETUP, {
      status: "running",
      fields: [field(GROUP_1.fieldKeys[0]!, "started")],
    }),
    deriveSetupItems(SETUP, { status: "complete", fast_budget_exhausted: true }),
  ];
  const ids = ticks.map((items) => items.map((item) => item.id).join(","));
  assert.equal(new Set(ids).size, 1);
});

/** The brand-kit row after a derivation, or `undefined` when the fixture dropped it. */
function brandKitRow(progress: Parameters<typeof deriveSetupItems>[1]) {
  return deriveSetupItems(SETUP, progress).find((item) => item.id === BRAND_KIT_ITEM_ID);
}

/** The fixture's own brand-kit detail line — the base every mapping keeps. */
const BRAND_KIT_DETAIL = SETUP.items.find((item) => item.id === BRAND_KIT_ITEM_ID)?.detail;

test("no ingestion job leaves the brand-kit row queued, and the fixture status never leaks", () => {
  // The fixture claims `running` for the design-review theatre; live truth is the only input.
  assert.equal(SETUP.items.find((item) => item.id === BRAND_KIT_ITEM_ID)?.status, "running");
  assert.equal(brandKitRow(null)?.status, "queued");
  assert.equal(brandKitRow({ status: "complete" })?.status, "queued");
  // A pre-slice payload carries no field at all; an explicit null says the same thing.
  assert.equal(brandKitRow({ status: "running", brand_kit_ingestion: null })?.status, "queued");
  assert.equal(brandKitRow({ status: "running" })?.detail, BRAND_KIT_DETAIL);
});

test("a queued or running ingestion job runs the brand-kit row", () => {
  for (const status of ["queued", "running"]) {
    const row = brandKitRow({
      status: "running",
      brand_kit_ingestion: { job_id: "ingest_1", status },
    });
    assert.equal(row?.status, "running", `job ${status} must read as running`);
    assert.equal(row?.detail, BRAND_KIT_DETAIL);
  }
});

test("a succeeded ingestion job completes the brand-kit row", () => {
  const row = brandKitRow({
    status: "running",
    brand_kit_ingestion: { job_id: "ingest_1", status: "succeeded" },
  });
  assert.equal(row?.status, "complete");
  assert.equal(row?.detail, BRAND_KIT_DETAIL);
});

test("a failed ingestion job annotates instead of claiming a kit exists", () => {
  // The row vocabulary has no failed state: `complete` would claim a kit nothing produced, so
  // the failure rides the detail line — the same idiom a failed recon field uses.
  const row = brandKitRow({
    status: "complete",
    brand_kit_ingestion: { job_id: "ingest_1", status: "failed" },
  });
  assert.equal(row?.status, "queued");
  assert.equal(row?.detail, `${BRAND_KIT_DETAIL}${FAILED_MEMBER_ANNOTATION}`);
});

test("an unrecognized job status reads as in-flight, never as a kit that exists", () => {
  const row = brandKitRow({
    status: "running",
    brand_kit_ingestion: { job_id: "ingest_1", status: "some-future-status" },
  });
  assert.equal(row?.status, "running");
  assert.equal(row?.detail, BRAND_KIT_DETAIL);
});

test("the brand-kit row is independent of the recon groups it sits under", () => {
  // The warm-up rule is index-0-only and the group reduction never sees the job: a released,
  // fully-complete recon run with a still-running ingestion keeps the two truths separate.
  const items = deriveSetupItems(SETUP, {
    status: "complete",
    brand_kit_ingestion: { job_id: "ingest_1", status: "running" },
  });
  assert.deepEqual(
    items.map((item) => item.status),
    ["complete", "complete", "complete", "complete", "running"],
  );
  // …and a halted recon run does not demote a kit that genuinely published.
  const halted = deriveSetupItems(SETUP, {
    status: "failed",
    brand_kit_ingestion: { job_id: "ingest_1", status: "succeeded" },
  });
  assert.deepEqual(
    halted.map((item) => item.status),
    ["queued", "queued", "queued", "queued", "complete"],
  );
  // The warm-up row stays the first GROUP even when the brand kit is the only thing moving.
  const warming = deriveSetupItems(SETUP, {
    status: "starting",
    brand_kit_ingestion: { job_id: "ingest_1", status: "queued" },
  });
  assert.equal(warming[0]?.id, SETUP_GROUPS[0]?.id);
  assert.equal(warming[0]?.status, "running");
});

test("a fixture without the brand-kit row drops it cleanly", () => {
  const withoutBrandKit = {
    ...SETUP,
    items: SETUP.items.filter((item) => item.id !== BRAND_KIT_ITEM_ID),
  };
  const items = deriveSetupItems(withoutBrandKit, null);
  assert.equal(items.length, 4);
});

test("the group table is a parameter, not a hard-wired dependency", () => {
  const table: readonly SetupGroup[] = [
    { id: "solo", label: "Solo", detail: "One field", fieldKeys: ["client.product"] },
  ];
  const items = deriveSetupItems(
    SETUP,
    { status: "running", fields: [field("client.product", "resolved")] },
    table,
  );
  assert.equal(items.length, 2);
  assert.equal(items[0]?.id, "solo");
  assert.equal(items[0]?.status, "complete");
});

test("groupStatus is a pure reduction over member events and run truth", () => {
  assert.equal(groupStatus([], GROUP_1, { status: "running" }), "queued");
  assert.equal(groupStatus([], GROUP_1, { status: "complete" }), "complete");
  assert.equal(
    groupStatus([field(GROUP_1.fieldKeys[0]!, "started")], GROUP_1, { status: "running" }),
    "running",
  );
  // A field outside the group never moves it.
  assert.equal(
    groupStatus([field(GROUP_2.fieldKeys[0]!, "resolved")], GROUP_1, { status: "running" }),
    "queued",
  );
  // Lane truth is part of the reduction, not just the overall status.
  assert.equal(
    groupStatus([field(GROUP_1.fieldKeys[0]!, "started")], GROUP_1, {
      status: "running",
      fast_status: "paused",
    }),
    "queued",
  );
});
