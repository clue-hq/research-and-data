import assert from "node:assert/strict";
import test from "node:test";
import { existsSync } from "node:fs";
import { createDirectMailFixture } from "./direct-mail.fixture";
import { approveMailers, readiness, reviewMailer, updateMailer, noteFits, matchingCardArtwork, StateSchema } from "../model/direct-mail";
import { HARVEY_DEMO_ID, withHarveyDemo, advanceHarveyDemo, resetHarveyDemo } from "./harvey-demo";
import { createDirectMailRepository, unavailableDirectMailRepository } from "./direct-mail.repository";
import type { DirectMailStore } from "./direct-mail.storage";
import { HARVEY_DELIVERED_ID } from "../model/harvey-demo-context";
import { estimate } from "../model/direct-mail";
import { readPendingDraft, writePendingDraft } from "./direct-mail.drafts";

const seed = () => withHarveyDemo(createDirectMailFixture());
const current = (state: ReturnType<typeof seed>) => state.mailers.find(m => m.id === HARVEY_DEMO_ID)!;
function approved() {
  let state = seed(), m = current(state);
  state = updateMailer(state, m.id, m.revision, { addressConfirmed: true });
  m = current(state);
  assert.deepEqual(readiness(m, state), []);
  state = reviewMailer(state, m.id, m.revision);
  m = current(state);
  return approveMailers(state, [{ id: m.id, revision: m.revision }]).state;
}

test("recording seed is additive and preserves edits on subsequent reads", () => {
  const before = createDirectMailFixture(), state = withHarveyDemo(before);
  assert.deepEqual(state.mailers.filter(m => ![HARVEY_DEMO_ID, HARVEY_DELIVERED_ID].includes(m.id)), before.mailers);
  current(state).note = "My edit";
  const again = withHarveyDemo(state);
  assert.equal(again.mailers.filter(m => m.id === HARVEY_DEMO_ID).length, 1);
  assert.equal(current(again).note, "My edit");
  assert.equal(current(again).recipient.company, "Benesch");
  assert.equal(current(again).projectName, "Harvey new logo acquisition");
  for (const g of current(again).gifts) {
    assert.match(g.productUrl!, /^https:\/\/woodpeck.com\/products\/.+\?variant=\d+$/);
    assert.equal(existsSync(`public${g.image}`), true);
  }
});

test("approval requires an explicit demo address acknowledgment", () => {
  const state = seed();
  assert.equal(current(state).addressConfirmed, false);
  assert.throws(() => reviewMailer(state, HARVEY_DEMO_ID, 1), /address/i);
});

test("simulation rejects unapproved, unrelated and stale records", () => {
  const state = seed();
  assert.throws(() => advanceHarveyDemo(state, HARVEY_DEMO_ID, 1), /approval/i);
  assert.throws(() => advanceHarveyDemo(state, "mailer-avery", 1), /demo/i);
  const ready = approved();
  assert.throws(() => advanceHarveyDemo(ready, HARVEY_DEMO_ID, 1), /changed/i);
});

test("approved simulation preserves purchase snapshot and uses no fake carrier links or photos", () => {
  let state = approved();
  const approval = structuredClone(current(state).approval);
  for (const stage of ["ordered", "inbound", "received", "preparing", "ready_to_ship", "shipped", "delivered"]) {
    const m = current(state);
    state = advanceHarveyDemo(state, m.id, m.revision);
    assert.equal(current(state).stage, stage);
    assert.deepEqual(current(state).approval, approval);
    assert.deepEqual(current(state).photos, []);
    assert.equal(current(state).inbound?.trackingUrl ?? null, null);
    assert.equal(current(state).outbound?.trackingUrl ?? null, null);
    assert.match(current(state).events.at(-1)!.detail, /simulat/i);
  }
  assert.throws(() => advanceHarveyDemo(state, HARVEY_DEMO_ID, current(state).revision), /complete/i);
});

test("replay reset restores only this mailer, refunds its net debit once, and keeps revisions monotonic", () => {
  const initial = seed();
  let state = approved();
  const others = structuredClone(state.mailers.filter(m => m.id !== HARVEY_DEMO_ID));
  const oldRevision = current(state).revision;
  state = resetHarveyDemo(state, HARVEY_DEMO_ID, oldRevision);
  assert.equal(current(state).stage, "needs_review");
  assert.equal(current(state).addressConfirmed, false);
  assert.equal(current(state).revision, oldRevision + 1);
  assert.equal(state.creditBalanceCents, initial.creditBalanceCents);
  assert.deepEqual(state.mailers.filter(m => m.id !== HARVEY_DEMO_ID), others);
  const balance = state.creditBalanceCents;
  assert.throws(() => resetHarveyDemo(state, HARVEY_DEMO_ID, oldRevision), /changed/i);
  state = resetHarveyDemo(state, HARVEY_DEMO_ID, current(state).revision);
  assert.equal(state.creditBalanceCents, balance);
});

test("only the enabled V2 recording repository exposes replay operations", async () => {
  let state = approved();
  const store: DirectMailStore = { async read() { return structuredClone(state); }, async transact(change) { const next = change(structuredClone(state)); state = next.state; return next.result; } };
  assert.equal(createDirectMailRepository(store).advanceDemo, undefined);
  assert.equal(unavailableDirectMailRepository.resetDemo, undefined);
  const repo = createDirectMailRepository(store, undefined, true);
  const before = current(state);
  await repo.advanceDemo!(before.id, before.revision);
  assert.equal(current(await repo.read()).stage, "ordered");
  await assert.rejects(repo.advanceDemo!(before.id, before.revision), /changed/);
});

test("a canceled approval cannot double-refund credits when the take resets", async () => {
  let state = approved();
  const balance = seed().creditBalanceCents;
  const store: DirectMailStore = { async read() { return structuredClone(state); }, async transact(change) { const next = change(structuredClone(state)); state = next.state; return next.result; } };
  const repo = createDirectMailRepository(store, undefined, true);
  let m = current(state);
  await repo.cancel(m.id, m.revision);
  m = current(state);
  await repo.resetDemo!(m.id, m.revision);
  assert.equal(state.creditBalanceCents, balance);
});

test("successful reset clears only this tab's recording draft, failed reset retains it", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) } });
  try {
    let state = seed();
    const store: DirectMailStore = { async read() { return structuredClone(state); }, async transact(change) { const next = change(structuredClone(state)); state = next.state; return next.result; } };
    const repo = createDirectMailRepository(store, undefined, true);
    writePendingDraft(HARVEY_DEMO_ID, { revision: 1, patch: { note: "Unsaved take" } });
    writePendingDraft("mailer-avery", { revision: 1, patch: { note: "Keep this" } });
    await assert.rejects(repo.resetDemo!(HARVEY_DEMO_ID, 999), /changed/);
    assert.equal(readPendingDraft(HARVEY_DEMO_ID)?.patch.note, "Unsaved take");
    await repo.resetDemo!(HARVEY_DEMO_ID, 1);
    assert.equal(readPendingDraft(HARVEY_DEMO_ID), null);
    assert.equal(readPendingDraft("mailer-avery")?.patch.note, "Keep this");
  } finally {
    if (previous) Object.defineProperty(globalThis, "sessionStorage", previous);
    else Reflect.deleteProperty(globalThis, "sessionStorage");
  }
});


test("delivered example is additive, has a complete approved snapshot and does not debit credits", () => {
  const before = createDirectMailFixture(), state = withHarveyDemo(before);
  const m = state.mailers.find(m => m.id === HARVEY_DELIVERED_ID)!;
  assert.equal(m.stage, "delivered");
  assert.equal(m.approval?.estimatedCents, estimate(m));
  assert.equal(estimate(m), 12950);
  assert.equal(m.approval?.note, m.note);
  assert.equal(m.approval?.card.id, "card-harvey-demo");
  assert.equal(m.outbound?.trackingUrl, null);
  assert.equal(m.events.length, 8);
  assert.equal(state.creditBalanceCents, before.creditBalanceCents);
  assert.deepEqual(state.creditEntries, before.creditEntries);
  assert.deepEqual(withHarveyDemo(state), state);
  for (const gift of m.gifts) assert.ok(existsSync(`public${gift.image}`));
});

test("physical-card refresh preserves recording progress, edited text and financial history", () => {
  const before = approved(), mailer = current(before);
  const legacyCard = { ...before.cards.find(c => c.id === mailer.cardId)!, version: 1, frontUrl: "/direct-mail/harvey-demo/card.svg", paper: "white" as const };
  before.cards = before.cards.map(c => c.id === legacyCard.id ? legacyCard : c);
  mailer.styleId = "style-warm";
  mailer.note = "Keep this edited message";
  mailer.approval!.card = structuredClone(legacyCard);
  mailer.approval!.style = structuredClone(before.styles.find(s => s.id === "style-warm")!);
  const after = withHarveyDemo(before), updated = current(after);
  assert.equal(updated.note, mailer.note);
  assert.equal(updated.styleId, "style-harvey-handprint");
  assert.equal(updated.approval!.card.version, 3);
  assert.equal(updated.approval!.card.paper, "cream");
  assert.equal(updated.approval!.style.family, "Clue Handprint");
  assert.ok(existsSync(`public${updated.approval!.card.frontUrl}`));
  // The only differences are the requested card and lettering; the send stays intact.
  assert.deepEqual({ ...updated, styleId: mailer.styleId, approval: { ...updated.approval, card: mailer.approval!.card, style: mailer.approval!.style } }, mailer);
  assert.deepEqual(after.creditEntries, before.creditEntries);
  assert.equal(after.creditBalanceCents, before.creditBalanceCents);
  assert.deepEqual(after.mailers.filter(m => m.id !== HARVEY_DEMO_ID), before.mailers.filter(m => m.id !== HARVEY_DEMO_ID));
  assert.deepEqual(withHarveyDemo(after), after);
  // A later deliberate handwriting choice must survive reads.
  updated.styleId = "style-warm";
  assert.equal(current(withHarveyDemo(after)).styleId, "style-warm");
});

test("both recording messages fit the physical-card layout with upright handwriting", () => {
  const state = seed();
  for (const mailer of state.mailers.filter(m => [HARVEY_DEMO_ID, HARVEY_DELIVERED_ID].includes(m.id))) {
    const card = state.cards.find(c => c.id === mailer.cardId)!;
    const style = state.styles.find(s => s.id === mailer.styleId)!;
    assert.equal(style.family, "Clue Handprint");
    assert.equal(noteFits(mailer.note, mailer.signature, card, style), true);
  }
});


test("handwritten images match exact recipient text, signature and style; edits never show stale art", () => {
  const state = seed();
  for (const mailer of state.mailers.filter(m => [HARVEY_DEMO_ID, HARVEY_DELIVERED_ID].includes(m.id))) {
    const card = state.cards.find(c => c.id === mailer.cardId)!;
    const style = state.styles.find(s => s.id === mailer.styleId)!;
    const artwork = matchingCardArtwork(card, style, mailer.note, mailer.signature);
    assert.ok(artwork);
    assert.ok(existsSync(`public${artwork.url}`));
    assert.equal(matchingCardArtwork(card, style, mailer.note + "Edited", mailer.signature), undefined);
    assert.equal(matchingCardArtwork(card, style, mailer.note, "Different sender"), undefined);
    assert.equal(matchingCardArtwork(card, state.styles[0], mailer.note, mailer.signature), undefined);
    assert.equal(card.branding?.qrDestination, "https://www.harvey.ai/");
    assert.ok(existsSync(`public${card.branding?.qrImageUrl}`));
  }
});


test("saved card branding without an optional display name still hydrates", () => {
  const saved = JSON.parse(JSON.stringify(seed()));
  const card = saved.cards.find((c: { id: string }) => c.id === "card-harvey-demo");
  delete card.branding.name;
  const hydrated = StateSchema.parse(saved);
  assert.equal(hydrated.cards.find(c => c.id === card.id)?.branding?.name, "");
});
