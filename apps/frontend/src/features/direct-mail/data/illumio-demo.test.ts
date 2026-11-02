import assert from "node:assert/strict";
import test from "node:test";
import { existsSync } from "node:fs";
import { createIllumioDemo, illumioSimulation, parseIllumioDemo } from "./illumio-demo";
import { DEMO_ID, DEMO_ACCOUNT_ID, demoMaterials } from "../model/recording-demo-context";
import { approveMailers, estimate, matchingCardArtwork, reviewMailer, updateMailer } from "../model/direct-mail";

test("Illumio starts with exactly one sourced account and all local preview assets", () => {
  const state = createIllumioDemo(), m = state.mailers[0];
  assert.equal(state.mailers.length, 1);
  assert.equal(m.accountId, DEMO_ACCOUNT_ID);
  assert.equal(m.recipient.name, "Ann Barron-DiCamillo");
  assert.equal(estimate(m), 14200);
  for (const gift of m.gifts) {
    assert.ok(gift.productUrl?.includes("variant="));
    assert.ok(existsSync(`public${gift.image}`));
  }
  for (const material of demoMaterials) assert.ok(existsSync(`public${material.image}`));
  const card = state.cards[0], style = state.styles[0];
  const artwork = matchingCardArtwork(card, style, m.note, m.signature);
  assert.ok(artwork && existsSync(`public${artwork.url}`));
  assert.equal(matchingCardArtwork(card, style, m.note + "Edited", m.signature), undefined);
  for (const path of [card.frontUrl, card.branding!.logoUrl, card.branding!.markUrl, card.branding!.qrImageUrl]) assert.ok(existsSync(`public${path}`));
});

test("Illumio approval, fulfillment and replay preserve the selected product and card", () => {
  let state = createIllumioDemo();
  assert.throws(() => illumioSimulation.advance(state, DEMO_ID, 1), /approval/);
  state = updateMailer(state, DEMO_ID, 1, { addressConfirmed: true });
  state = reviewMailer(state, DEMO_ID, state.mailers[0].revision);
  const result = approveMailers(state, [{ id: DEMO_ID, revision: state.mailers[0].revision }]);
  assert.equal(result.results[0].ok, true);
  state = result.state;
  const snapshot = structuredClone(state.mailers[0].approval);
  for (const stage of ["ordered", "inbound", "received", "preparing", "ready_to_ship", "shipped", "delivered"]) {
    state = illumioSimulation.advance(state, DEMO_ID, state.mailers[0].revision);
    assert.equal(state.mailers[0].stage, stage);
    assert.deepEqual(state.mailers[0].approval, snapshot);
    assert.equal(state.mailers[0].outbound?.trackingUrl ?? null, null);
  }
  const revision = state.mailers[0].revision;
  state = illumioSimulation.reset(state, DEMO_ID, revision);
  assert.equal(state.mailers[0].stage, "needs_review");
  assert.equal(state.mailers[0].revision, revision + 1);
  assert.equal(state.creditBalanceCents, 200000);
  assert.equal(state.mailers[0].addressConfirmed, false);
  assert.throws(() => illumioSimulation.reset(state, "mailer-harvey-benesch-jason", revision), /demo/);
});

test("card front refresh preserves edits and requires review without changing approved snapshots", () => {
  const previous = createIllumioDemo();
  Object.assign(previous.cards[0], { version: 2, frontUrl: "/direct-mail/illumio-demo/illumio-hq.webp", frontLayout: "photograph" });
  previous.mailers[0].note = "An edited note";
  previous.mailers[0].addressConfirmed = true;
  const reviewed = reviewMailer(previous, DEMO_ID, previous.mailers[0].revision);
  const refreshed = parseIllumioDemo(reviewed);
  assert.equal(reviewed.cards[0].version, 2, "input is not mutated");
  assert.equal(refreshed.cards[0].version, 3);
  assert.equal(refreshed.cards[0].frontLayout, undefined);
  assert.equal(refreshed.mailers[0].note, "An edited note");
  assert.equal(refreshed.mailers[0].stage, "needs_review");
  assert.equal(refreshed.mailers[0].reviewedRevision, null);
  assert.equal(refreshed.mailers[0].revision, reviewed.mailers[0].revision + 1);
  assert.deepEqual(parseIllumioDemo(refreshed), refreshed, "refresh is idempotent");

  const approved = approveMailers(reviewed, [{ id: DEMO_ID, revision: reviewed.mailers[0].revision }]).state;
  assert.deepEqual(parseIllumioDemo(approved).mailers, approved.mailers);
  assert.deepEqual(parseIllumioDemo(approved).creditEntries, approved.creditEntries);
  const custom = structuredClone(previous);
  custom.cards[0].frontUrl = "/custom-front.png";
  assert.deepEqual(parseIllumioDemo(custom), custom, "custom fronts are retained");
});

test("display copy refresh preserves custom content, selections and approved records", () => {
  const oldReason = "A collection that can be shared with the team, with several different challenges in one box. Choose it for a shared break rather than an individual desk piece.";
  const state = createIllumioDemo();
  const mailer = state.mailers[0];
  mailer.gifts[2].rationale = oldReason;
  mailer.gifts[0].rationale = "A customized recommendation";
  mailer.insight.detail = "Custom research context";
  mailer.note = "An edited note";
  mailer.selectedGiftId = mailer.gifts[2].id;
  mailer.addressConfirmed = true;
  const refreshed = parseIllumioDemo(state);
  assert.equal(refreshed.mailers[0].gifts[2].rationale, createIllumioDemo().mailers[0].gifts[2].rationale);
  const expected = structuredClone(state);
  expected.mailers[0].gifts[2].rationale = refreshed.mailers[0].gifts[2].rationale;
  assert.deepEqual(refreshed, expected, "only the old built-in wording changes");
  assert.deepEqual(parseIllumioDemo(refreshed), refreshed, "refresh is idempotent");
  const reviewed = reviewMailer(state, DEMO_ID, mailer.revision);
  const approved = approveMailers(reviewed, [{ id: DEMO_ID, revision: reviewed.mailers[0].revision }]).state;
  assert.ok(approved.mailers[0].approval);
  assert.deepEqual(parseIllumioDemo(approved), approved, "approved records and credit history are unchanged");
});
