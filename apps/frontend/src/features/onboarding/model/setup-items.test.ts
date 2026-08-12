import assert from "node:assert/strict";
import test from "node:test";
import { onboardingFixture } from "../data/onboarding.fixture";
import { BRAND_KIT_ITEM_ID, deriveSetupItems, laneItemStatus } from "./setup-items";

const SETUP = onboardingFixture.setup;

test("laneItemStatus covers every real recon lane status explicitly", () => {
  assert.equal(laneItemStatus("queued"), "queued");
  assert.equal(laneItemStatus("running"), "running");
  assert.equal(laneItemStatus("completed"), "complete");
  // failed/paused must NOT read as queued — that would assert "this will happen".
  assert.equal(laneItemStatus("failed"), "stopped");
  assert.equal(laneItemStatus("paused"), "stopped");
  assert.equal(laneItemStatus(null), "queued");
});

test("pre-first-poll derivation renders queued rows plus the dummy brand kit", () => {
  const items = deriveSetupItems(SETUP, null);
  assert.equal(items.length, 3);
  assert.deepEqual(
    items.map((item) => item.status),
    ["queued", "queued", "queued"],
  );
  const brandKit = items.find((item) => item.id === BRAND_KIT_ITEM_ID);
  assert.ok(brandKit);
  assert.equal(brandKit.label, "Creating brand kit");
});

test("starting shows motion on the fast row; lane truth drives the rest", () => {
  const starting = deriveSetupItems(SETUP, {
    status: "starting",
    fast_status: null,
    background_status: null,
  });
  assert.equal(starting[0]?.status, "running");

  const live = deriveSetupItems(SETUP, {
    status: "complete",
    fast_status: "completed",
    background_status: "running",
  });
  assert.equal(live[0]?.status, "complete");
  assert.equal(live[1]?.status, "running");
});

test("a stopped background lane is annotated honestly, never claimed as pending work", () => {
  const items = deriveSetupItems(SETUP, {
    status: "complete",
    fast_status: "completed",
    background_status: "failed",
  });
  assert.match(items[1]?.detail ?? "", /Didn't finish/);
});

test("the brand-kit dummy is forced queued even when the fixture claims running", () => {
  const fixtureBrandKit = SETUP.items.find((item) => item.id === BRAND_KIT_ITEM_ID);
  assert.equal(fixtureBrandKit?.status, "running");
  const items = deriveSetupItems(SETUP, null);
  assert.equal(items.find((item) => item.id === BRAND_KIT_ITEM_ID)?.status, "queued");
});

test("a fixture without the brand-kit row drops it cleanly", () => {
  const withoutBrandKit = {
    ...SETUP,
    items: SETUP.items.filter((item) => item.id !== BRAND_KIT_ITEM_ID),
  };
  const items = deriveSetupItems(withoutBrandKit, null);
  assert.equal(items.length, 2);
});
