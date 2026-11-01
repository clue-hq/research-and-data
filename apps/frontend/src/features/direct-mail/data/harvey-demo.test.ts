import assert from "node:assert/strict";
import test from "node:test";
import { existsSync } from "node:fs";
import { createDirectMailFixture } from "./direct-mail.fixture";
import { approveMailers, readiness, reviewMailer, updateMailer } from "../model/direct-mail";
import { HARVEY_DEMO_ID, withHarveyDemo, advanceHarveyDemo, resetHarveyDemo } from "./harvey-demo";
import { createDirectMailRepository, unavailableDirectMailRepository } from "./direct-mail.repository";
import type { DirectMailStore } from "./direct-mail.storage";
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
  assert.deepEqual(state.mailers.filter(m => m.id !== HARVEY_DEMO_ID), before.mailers);
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
