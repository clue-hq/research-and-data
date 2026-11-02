import assert from "node:assert/strict";
import test from "node:test";
import { existsSync } from "node:fs";
import { createIllumioDemo, illumioSimulation } from "./illumio-demo";
import { DEMO_ID, DEMO_ACCOUNT_ID, demoMaterials } from "../model/recording-demo-context";
import { approveMailers, estimate, matchingCardArtwork, reviewMailer, updateMailer } from "../model/direct-mail";

test("Illumio starts with exactly one sourced account and all local preview assets", () => {
  const state = createIllumioDemo(), m = state.mailers[0];
  assert.equal(state.mailers.length, 1);
  assert.equal(m.accountId, DEMO_ACCOUNT_ID);
  assert.equal(m.recipient.name, "Ann Barron-DiCamillo");
  assert.equal(estimate(m), 13399);
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
