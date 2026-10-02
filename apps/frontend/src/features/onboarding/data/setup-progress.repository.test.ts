import assert from "node:assert/strict";
import test from "node:test";
import { SETUP_GROUPS } from "./setup-groups";
import {
  SetupStatusSchema,
  readSetupStatus,
  startWorkspaceSetup,
  type SetupStatus,
} from "./setup";
import { FIXTURE_SETUP_PROGRESS_SCRIPT } from "./setup-progress.fixture";
import {
  createFixtureSetupProgressSource,
  httpSetupProgressSource,
} from "./setup-progress.repository";
import { BRAND_KIT_ITEM_ID, CONTINUING_ANNOTATION, deriveSetupItems } from "../model/setup-items";
import type { OnboardingFlow, SetupItem } from "../model/onboarding";

const STATUS_RANK: Record<SetupItem["status"], number> = {
  queued: 0,
  running: 1,
  complete: 2,
};

const FIXTURE_SETUP: OnboardingFlow["setup"] = {
  title: "Setting up",
  finalizingDetail: "Finalizing",
  // No brand-kit row: this test is about the durable groups, not the ratified dummy.
  items: [{ id: "unused", label: "unused", detail: "unused", status: "queued" }],
};

/** The same fixture WITH the brand-kit row, for the one assertion that is about that row. */
const FIXTURE_SETUP_WITH_BRAND_KIT: OnboardingFlow["setup"] = {
  ...FIXTURE_SETUP,
  items: [
    ...FIXTURE_SETUP.items,
    { id: BRAND_KIT_ITEM_ID, label: "Creating brand kit", detail: "Colours and type", status: "queued" },
  ],
};

/** The checklist as the screen would render it for a given frame, keyed by row id. */
function rowsOf(frame: SetupStatus | null): Record<string, SetupItem> {
  return Object.fromEntries(
    deriveSetupItems(FIXTURE_SETUP, frame).map((item) => [item.id, item]),
  );
}

test("the http source delegates to the existing transport functions, unmoved", () => {
  // Identity, not behaviour: `data/setup.test.ts` owns what those two functions do on the wire.
  // What this seam promises is that it adds nothing between the hook and them.
  assert.equal(httpSetupProgressSource.start, startWorkspaceSetup);
  assert.equal(httpSetupProgressSource.read, readSetupStatus);
});

test("the fixture source replays its script frame per read and sticks at the last frame", async () => {
  const script: SetupStatus[] = [
    SetupStatusSchema.parse({ status: "starting" }),
    SetupStatusSchema.parse({ status: "running" }),
    SetupStatusSchema.parse({ status: "complete" }),
  ];
  const source = createFixtureSetupProgressSource(script);

  assert.equal((await source.read()).status, "starting");
  assert.equal((await source.read()).status, "running");
  assert.equal((await source.read()).status, "complete");
  // Sticks: the stream has no further state, and time alone never invents one.
  assert.equal((await source.read()).status, "complete");
  assert.equal((await source.read()).status, "complete");
});

test("the fixture source's start is not a read: it consumes no frame", async () => {
  const source = createFixtureSetupProgressSource([
    SetupStatusSchema.parse({ status: "starting" }),
    SetupStatusSchema.parse({ status: "running" }),
  ]);
  // The website is accepted and ignored — a scripted stream researches nobody.
  await source.start({ companyWebsite: "https://cluehq.ai" });
  await source.start({ companyWebsite: "" });
  assert.equal((await source.read()).status, "starting");
});

test("the fixture source validates every frame through the same schema the http path uses", async () => {
  const wireFrame = {
    status: "some-future-status",
    steps: [{ kind: "overview", status: "who-knows" }],
  } as unknown as SetupStatus;
  const source = createFixtureSetupProgressSource([wireFrame]);
  const frame = await source.read();
  // Exactly the http path's degradations (review FE-N2), because it is the same parse.
  assert.equal(frame.status, "unavailable");
  assert.equal(frame.steps[0]?.status, "running");
  assert.equal(frame.run_id, null);
});

test("an empty fixture script fails loudly rather than serving nothing", () => {
  assert.throws(() => createFixtureSetupProgressSource([]), /at least one frame/);
});

test("every default-script frame parses through SetupStatusSchema unchanged", () => {
  assert.ok(FIXTURE_SETUP_PROGRESS_SCRIPT.length > 1);
  for (const frame of FIXTURE_SETUP_PROGRESS_SCRIPT) {
    const parsed = SetupStatusSchema.parse(frame);
    // Wire-shaped: parsing is a no-op, so the fixture cannot drift from the wire contract.
    assert.deepEqual(parsed, frame);
  }
});

test("the default script moves: each frame differs from the one before it", () => {
  for (let index = 1; index < FIXTURE_SETUP_PROGRESS_SCRIPT.length; index += 1) {
    assert.notDeepEqual(
      FIXTURE_SETUP_PROGRESS_SCRIPT[index],
      FIXTURE_SETUP_PROGRESS_SCRIPT[index - 1],
      `frame ${index} repeats its predecessor — the poll tick would render no motion`,
    );
  }
});

test("the scripted run walks the checklist from warm-up to release, through the seam", async () => {
  const source = createFixtureSetupProgressSource();

  // Frame 1 — queued, no step has reported: the first row warms up and nothing else is claimed.
  const queued = rowsOf(await source.read());
  assert.equal(queued.company?.status, "running");
  assert.deepEqual(
    SETUP_GROUPS.slice(1).map((group) => queued[group.id]?.status),
    ["queued", "queued", "queued"],
  );

  // Frame 2 — the three fast reads are out together; the ICP turn has not been reached.
  const fanOut = rowsOf(await source.read());
  assert.equal(fanOut.company?.status, "running");
  assert.equal(fanOut.products?.status, "running");
  assert.equal(fanOut.proof?.status, "running");
  assert.equal(fanOut.audience?.status, "queued");

  // Frame 3 — the reads answered (`empty` for reviews is a correct terminal, so proof is done)
  // and the ICP turn is in flight.
  const synthesizing = rowsOf(await source.read());
  assert.equal(synthesizing.company?.status, "complete");
  assert.equal(synthesizing.products?.status, "complete");
  assert.equal(synthesizing.proof?.status, "complete");
  assert.equal(synthesizing.audience?.status, "running");

  // Frame 4 — release. Every row is complete, and the audience row says so honestly: its lead
  // step is done while per-persona work continues behind the user.
  const released = rowsOf(await source.read());
  assert.equal(FIXTURE_SETUP_PROGRESS_SCRIPT[3]?.status, "complete");
  assert.ok(SETUP_GROUPS.every((group) => released[group.id]?.status === "complete"));
  assert.ok((released.audience?.detail ?? "").endsWith(CONTINUING_ANNOTATION));
  assert.ok(
    SETUP_GROUPS.filter((group) => group.id !== "audience").every(
      (group) => !(released[group.id]?.detail ?? "").includes(CONTINUING_ANNOTATION),
    ),
    "only the audience row promises continuing work",
  );

  // The brand-kit row moves on the same truth the live read now serves: the ingestion fires
  // with the run and has published its draft kit by the release.
  const releaseFrame = FIXTURE_SETUP_PROGRESS_SCRIPT[FIXTURE_SETUP_PROGRESS_SCRIPT.length - 1]!;
  assert.equal(releaseFrame.brand_kit_ingestion?.status, "succeeded");
  const withBrandKit = deriveSetupItems(FIXTURE_SETUP_WITH_BRAND_KIT, releaseFrame);
  assert.equal(withBrandKit.find((item) => item.id === BRAND_KIT_ITEM_ID)?.status, "complete");

  // The stream sticks on the release frame: the hook releases here and never polls again.
  assert.deepEqual(rowsOf(await source.read()), released);
});

test("the derived checklist advances monotonically across the whole default script", async () => {
  const source = createFixtureSetupProgressSource();
  const seen: Record<string, number> = {};
  let sawRunning = false;
  for (let index = 0; index < FIXTURE_SETUP_PROGRESS_SCRIPT.length; index += 1) {
    const items = deriveSetupItems(FIXTURE_SETUP, await source.read());
    assert.equal(items.length, SETUP_GROUPS.length);
    for (const item of items) {
      const rank = STATUS_RANK[item.status];
      if (item.status === "running") sawRunning = true;
      assert.ok(
        rank >= (seen[item.id] ?? 0),
        `${item.id} regressed to ${item.status} at frame ${index}`,
      );
      seen[item.id] = rank;
    }
  }
  assert.ok(sawRunning, "the script never rendered a running row");
  assert.ok(
    SETUP_GROUPS.every((group) => seen[group.id] === STATUS_RANK.complete),
    "the script ended with an unfinished checklist row",
  );
});

test("every checklist group's lead step is reached by the default script", () => {
  const kinds = new Set(
    FIXTURE_SETUP_PROGRESS_SCRIPT.flatMap((frame) => frame.steps.map((s) => s.kind)),
  );
  // A row the script never feeds would go complete only on the release frame's blanket rule —
  // green for the wrong reason.
  assert.ok(SETUP_GROUPS.every((group) => kinds.has(group.stepKinds[0] ?? "")));
});
