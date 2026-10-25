import assert from "node:assert/strict";
import test from "node:test";
import { createDirectMailFixture } from "../data/direct-mail.fixture";
import { approveMailers, estimate, readiness, reviewMailer, updateMailer, StateSchema } from "./direct-mail";

function readyState() {
  let state = createDirectMailFixture();
  state = updateMailer(state, "mailer-avery", 1, { selectedGiftId: "field-notebook", addressConfirmed: true });
  return reviewMailer(state, "mailer-avery", 2);
}

test("unselected or incomplete recommendations cannot be reviewed", () => {
  const state = createDirectMailFixture();
  const mailer = state.mailers[0];
  assert.equal(mailer.selectedGiftId, null);
  assert.ok(readiness(mailer, state).some((reason) => /gift/i.test(reason)));
  assert.throws(() => reviewMailer(state, mailer.id, mailer.revision), /gift/i);
  assert.equal(StateSchema.safeParse({ ...state, mailers: [{ ...mailer, gifts: mailer.gifts.slice(0, 2) }] }).success, false);
});

test("unknown costs, unavailable gifts, missing address and note overflow block approval", () => {
  const state = readyState();
  const mailer = state.mailers[0];
  assert.equal(estimate(mailer), 7200);
  for (const broken of [
    { ...mailer, outboundCents: null },
    { ...mailer, gifts: mailer.gifts.map((gift) => ({ ...gift, available: false })) },
    { ...mailer, address: { ...mailer.address, line1: "" } },
    { ...mailer, note: "A very long note. ".repeat(100) },
    { ...mailer, budgetCents: 1000 },
  ]) assert.ok(readiness(broken, state).length > 0);
});

test("editing a reviewed mailer invalidates review and outdated writes are rejected", () => {
  const state = readyState();
  const mailer = state.mailers[0];
  assert.equal(mailer.stage, "ready");
  const changed = updateMailer(state, mailer.id, mailer.revision, { note: "A revised note." });
  assert.equal(changed.mailers[0].reviewedRevision, null);
  assert.equal(changed.mailers[0].stage, "needs_review");
  assert.throws(() => reviewMailer(changed, mailer.id, mailer.revision), /changed/i);
  assert.equal(approveMailers(changed, [{ id: mailer.id, revision: changed.mailers[0].revision }]).results[0].ok, false);
});

test("approval snapshots the exact mailer once and locks later edits", () => {
  const state = readyState();
  const mailer = state.mailers[0];
  const items = [{ id: mailer.id, revision: mailer.revision }];
  const approved = approveMailers(state, items);
  assert.equal(approved.results[0].ok, true);
  const record = approved.state.mailers[0];
  assert.equal(record.stage, "approved");
  assert.equal(record.approval?.gift.id, "field-notebook");
  assert.equal(record.approval?.estimatedCents, 7200);
  assert.equal(record.approval?.budgetCents, 10000);
  assert.equal(record.approval?.card.version, 1);
  const retried = approveMailers(approved.state, items);
  assert.equal(retried.results[0].ok, true);
  assert.deepEqual(retried.state.mailers[0], record);
  assert.throws(() => updateMailer(approved.state, record.id, record.revision, { note: "Overwrite" }), /approved/i);
});

test("bulk approval returns partial outcomes and never approves an unread record", () => {
  const state = readyState();
  const result = approveMailers(state, [
    { id: "mailer-avery", revision: state.mailers[0].revision },
    { id: "mailer-jordan", revision: 1 },
    { id: "unknown", revision: 1 },
  ]);
  assert.deepEqual(result.results.map((item) => item.ok), [true, false, false]);
  assert.equal(result.state.mailers.find((item) => item.id === "mailer-jordan")?.stage, "needs_review");
});

test("unverified uploaded assets and pending recommendation changes cannot be approved", () => {
  const state = readyState();
  state.cards[0].productionReady = false;
  assert.ok(readiness(state.mailers[0], state).some((reason) => /card/i.test(reason)));
  state.cards[0].productionReady = true;
  state.mailers[0].proposalRequest = { kind: "gifts", feedback: "Less expensive", requestedAt: "2026-10-25T00:00:00Z" };
  assert.ok(readiness(state.mailers[0], state).some((reason) => /recommendation/i.test(reason)));
});
