import assert from "node:assert/strict";
import test from "node:test";
import { existsSync } from "node:fs";
import { annGiftCatalog, previousAnnNotes } from "./illumio-gift-research";
import { createDirectMailRepository } from "./direct-mail.repository";
import { createIllumioDemo, illumioSimulation, parseIllumioDemo } from "./illumio-demo";
import { DEMO_ID, DEMO_ACCOUNT_ID, demoMaterials } from "../model/recording-demo-context";
import { approveMailers, estimate, matchingCardArtwork, noteNeedsGiftUpdate, readiness, reviewMailer, updateMailer } from "../model/direct-mail";

test("Illumio starts with exactly one sourced account and all local preview assets", () => {
  const state = createIllumioDemo(), m = state.mailers[0];
  assert.equal(state.mailers.length, 1);
  assert.equal(m.accountId, DEMO_ACCOUNT_ID);
  assert.equal(m.recipient.name, "Ann Barron-DiCamillo");
  assert.equal(estimate(m), 14200);
  for (const gift of m.gifts) {
    assert.ok(gift.productUrl?.startsWith("https://"));
    assert.ok(existsSync(`public${gift.image}`));
  }
  for (const gift of annGiftCatalog) {
    assert.ok(m.giftInsights?.some(i => i.id === gift.insightId && i.kind === "gift"));
    assert.ok(existsSync(`public${gift.image}`));
    const selected = updateMailer(state, m.id, m.revision, { selectedGiftId: gift.id, note: gift.suggestedNote!, addressConfirmed: true });
    assert.deepEqual(readiness(selected.mailers[0], selected), [], `${gift.name} has a fitting note and complete estimate`);
    const artwork = matchingCardArtwork(state.cards[0], state.styles[0], selected.mailers[0].note, m.signature);
    assert.ok(artwork && existsSync(`public${artwork.url}`), `${gift.name} has matching handwritten artwork`);
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
  mailer.gifts[2] = structuredClone(annGiftCatalog[4]);
  mailer.alternativeGifts = [structuredClone(annGiftCatalog[3]), structuredClone(annGiftCatalog[2])];
  mailer.gifts[2].rationale = oldReason;
  mailer.gifts[0].rationale = "A customized recommendation";
  mailer.insight.detail = "Custom research context";
  mailer.note = "An edited note";
  mailer.selectedGiftId = mailer.gifts[2].id;
  mailer.addressConfirmed = true;
  const refreshed = parseIllumioDemo(state);
  assert.equal(refreshed.mailers[0].gifts[2].rationale, annGiftCatalog[4].rationale);
  const expected = structuredClone(state);
  expected.mailers[0].gifts[2].rationale = refreshed.mailers[0].gifts[2].rationale;
  assert.deepEqual(refreshed, expected, "only the old built-in wording changes");
  assert.deepEqual(parseIllumioDemo(refreshed), refreshed, "refresh is idempotent");
  const reviewed = reviewMailer(state, DEMO_ID, mailer.revision);
  const approved = approveMailers(reviewed, [{ id: DEMO_ID, revision: reviewed.mailers[0].revision }]).state;
  assert.ok(approved.mailers[0].approval);
  assert.deepEqual(parseIllumioDemo(approved), approved, "approved records and credit history are unchanged");
});

test("new research migration retains old selections and custom notes without touching approvals", () => {
  const old = createIllumioDemo(), m = old.mailers[0];
  m.giftInsights = undefined; m.alternativeGifts = undefined;
  m.gifts = structuredClone([annGiftCatalog[0], annGiftCatalog[3], annGiftCatalog[4]]);
  m.gifts.forEach(g => { delete g.insightId; delete g.suggestedNote; });
  m.selectedGiftId = "museum-puzzles"; m.note = "A custom note"; m.addressConfirmed = true;
  m.gifts[0].rationale = "A custom reason";
  const migrated = parseIllumioDemo(old), current = migrated.mailers[0];
  assert.equal(current.selectedGiftId, "museum-puzzles");
  assert.equal(current.gifts.length, 3);
  assert.ok(current.alternativeGifts?.some(g => g.id === "lego-stem"));
  assert.equal(current.gifts[0].rationale, "A custom reason");
  assert.equal(current.note, "A custom note");
  assert.equal(current.giftInsights?.length, 4);
  assert.equal(current.revision, m.revision + 1);
  assert.deepEqual(parseIllumioDemo(migrated), migrated);
  const reviewed = reviewMailer(old, DEMO_ID, m.revision);
  const approved = approveMailers(reviewed, [{ id: DEMO_ID, revision: reviewed.mailers[0].revision }]).state;
  assert.deepEqual(parseIllumioDemo(approved), approved);
});

test("choosing an alternative keeps the recommendation and prior choice while updating the total", () => {
  const original = createIllumioDemo();
  let state = updateMailer(original, DEMO_ID, 1, { selectedGiftId: "archimedes-gear" });
  const m = state.mailers[0];
  assert.equal(m.selectedGiftId, "archimedes-gear");
  assert.equal(m.gifts.length, 3);
  assert.ok(m.gifts.some(g => g.id === "craighill-jack-brass"));
  assert.ok(m.alternativeGifts?.some(g => g.id === "lego-stem"));
  assert.equal(new Set([...m.gifts, ...m.alternativeGifts!].map(g => g.id)).size, 5);
  assert.equal(estimate(m), 7399);
  assert.throws(() => updateMailer(state, DEMO_ID, 1, { selectedGiftId: "lego-stem" }), /changed/);
  assert.throws(() => updateMailer(state, DEMO_ID, m.revision, { selectedGiftId: "invented-gift" }), /no longer/);
  state = updateMailer(state, DEMO_ID, m.revision, { selectedGiftId: "lego-stem" });
  assert.equal(state.mailers[0].selectedGiftId, "lego-stem");
  assert.ok(state.mailers[0].gifts.some(g => g.id === "archimedes-gear"));
  assert.equal(original.mailers[0].selectedGiftId, "craighill-jack-brass");
});

test("gift selection changes the note atomically; explicit mismatched wording still blocks approval", () => {
  let state = createIllumioDemo();
  state = updateMailer(state, DEMO_ID, 1, { selectedGiftId: "web-memoir", addressConfirmed: true });
  assert.match(state.mailers[0].note, /first HTML project/);
  assert.equal(noteNeedsGiftUpdate(state.mailers[0]), false);
  state = updateMailer(state, DEMO_ID, state.mailers[0].revision, { note: annGiftCatalog[0].suggestedNote! });
  assert.equal(noteNeedsGiftUpdate(state.mailers[0]), true);
  assert.ok(readiness(state.mailers[0], state).includes("Update the note to match the selected gift."));
  assert.throws(() => reviewMailer(state, DEMO_ID, state.mailers[0].revision), /note/);
  state = updateMailer(state, DEMO_ID, state.mailers[0].revision, { note: annGiftCatalog[1].suggestedNote! });
  assert.equal(noteNeedsGiftUpdate(state.mailers[0]), false);
  assert.deepEqual(readiness(state.mailers[0], state), []);
  state = updateMailer(state, DEMO_ID, state.mailers[0].revision, { note: "My own note", selectedGiftId: "lego-stem" });
  assert.equal(state.mailers[0].note, "My own note");
  assert.equal(noteNeedsGiftUpdate(state.mailers[0]), false);
});

test("refreshing built-in messages fixes a stale gift-note pairing without overwriting custom notes", () => {
  const old = createIllumioDemo();
  old.mailers[0].selectedGiftId = "lego-stem";
  old.mailers[0].note = previousAnnNotes[0];
  const next = parseIllumioDemo(old);
  assert.match(next.mailers[0].note, /learn by doing/);
  assert.equal(next.mailers[0].revision, old.mailers[0].revision + 1);
  assert.deepEqual(parseIllumioDemo(next), next);
  old.mailers[0].note = "My edited message";
  assert.equal(parseIllumioDemo(old).mailers[0].note, "My edited message");
});

test("alternative requests preserve sourced gifts and cannot load generic simulated research", async () => {
  let state = createIllumioDemo();
  const repo = createDirectMailRepository({ read: async () => structuredClone(state), transact: async change => { const result = change(structuredClone(state)); state = result.state; return result.result; } });
  const before = structuredClone(state.mailers[0]);
  state = await repo.requestProposal(DEMO_ID, 1, "gifts", "Keep the Jack Puzzle; find more practical options.");
  assert.equal(state.mailers[0].selectedGiftId, before.selectedGiftId);
  assert.deepEqual(state.mailers[0].gifts, before.gifts);
  assert.equal(state.mailers[0].note, before.note);
  await assert.rejects(repo.resolveProposal(DEMO_ID, state.mailers[0].revision, true), /not connected/);
  assert.ok(state.mailers[0].proposalRequest);
  state = await repo.resolveProposal(DEMO_ID, state.mailers[0].revision, false);
  assert.equal(state.mailers[0].proposalRequest, null);
  assert.deepEqual(state.mailers[0].giftInsights, before.giftInsights);
});
