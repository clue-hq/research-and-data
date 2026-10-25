import assert from "node:assert/strict";
import test from "node:test";
import { createDirectMailFixture } from "../data/direct-mail.fixture";
import { approveMailers, estimate, readiness, StateSchema } from "./direct-mail";
import { dollarsToCents, GiftBudgetSchema, noteTemplateBody, renderNoteTemplate, trackingMilestones } from "./direct-mail-context";
import { createDirectMailRepository } from "../data/direct-mail.repository";

test("legacy state survives extension without replacing notes or approvals", () => {
  const state = createDirectMailFixture();
  state.mailers[0].note = "My unsaved research-led message";
  const result = StateSchema.parse(JSON.parse(JSON.stringify(state)));
  assert.equal(result.mailers[0].note, state.mailers[0].note);
  assert.deepEqual(result.mailers[6].approval, state.mailers[6].approval);
});
test("search budgets guide gifts without approving mailers or reserving credits", async () => {
  let state = createDirectMailFixture();
  const before = state.creditBalanceCents;
  const repo = createDirectMailRepository({ read: async () => state, transact: async (change) => { const next = change(structuredClone(state)); state = next.state; return next.result; } });
  await repo.saveBudget({ projectId: state.mailers[0].projectId, revision: 1, minimumCents: 5000, preferredCents: 10000, ceilingCents: 12000, locked: true }, 0);
  assert.equal(state.creditBalanceCents, before);
  assert.equal(state.mailers[0].stage, "needs_review");
  assert.equal(state.mailers[0].approval, null);
  assert.equal(state.mailers[3].reviewedRevision, null);
  await assert.rejects(repo.saveBudget({ ...state.giftBudgets![0], preferredCents: 9000 }, 0), /changed/);
});
test("gift ceiling is hard while preferred minimum is advisory", () => {
  const state = createDirectMailFixture();
  state.giftBudgets = [{ projectId: state.mailers[3].projectId, revision: 1, minimumCents: 5000, preferredCents: 10000, ceilingCents: 12000, locked: true }];
  assert.equal(readiness(state.mailers[3], state).length, 0);
  state.mailers[3].gifts.find((g) => g.id === state.mailers[3].selectedGiftId)!.priceCents = 13000;
  assert.ok(readiness(state.mailers[3], state).some((issue) => issue.includes("gift-price ceiling")));
  assert.equal(GiftBudgetSchema.safeParse({ ...state.giftBudgets[0], minimumCents: 15000 }).success, false);
});
test("approval deducts the estimate once and insufficient credits refuse", () => {
  const state = createDirectMailFixture(), mailer = state.mailers[3];
  state.creditBalanceCents = 100000;
  const items = [{ id: mailer.id, revision: mailer.revision }];
  const first = approveMailers(state, items), retry = approveMailers(first.state, items);
  assert.equal(first.results[0].ok, true);
  assert.equal(first.state.creditBalanceCents, 100000 - estimate(mailer)!);
  assert.equal(retry.state.creditBalanceCents, first.state.creditBalanceCents);
  state.creditBalanceCents = 1;
  assert.equal(approveMailers(state, items).results[0].ok, false);
});
test("templates render recipient context without changing their saved source", () => {
  const m = createDirectMailFixture().mailers[3];
  const body = "Hi {{first_name}},\nA {{gift}} for {{company}}.";
  assert.equal(renderNoteTemplate(body, m), "Hi Sam,\nA Linen field notebook for Northstar Systems.");
  assert.equal(body.includes("{{first_name}}"), true);
  assert.throws(() => renderNoteTemplate("Hi {{unknown}}", m), /unsupported/i);
});
test("tracking keeps the merchant leg before preparation and outbound delivery", () => {
  const m = createDirectMailFixture().mailers[4];
  const steps = trackingMilestones(m);
  assert.deepEqual(steps.map((s) => s.id), ["ordered", "inbound", "received", "preparing", "shipped", "delivered"]);
  assert.equal(steps[1].state, "current");
  assert.equal(steps[4].state, "pending");
  m.stage = "canceled";
  assert.equal(trackingMilestones(m).some((s) => s.state === "current"), false);
});

test("saving a pilot-style salutation removes the original recipient", () => {
  const m = createDirectMailFixture().mailers[0];
  m.note = "Avery,\nA note for Northstar Systems.";
  assert.equal(noteTemplateBody(m), "{{first_name}},\nA note for {{company}}.");
});

test("decimal budget inputs convert to exact integer cents", () => {
  assert.equal(dollarsToCents("19.99"), 1999);
  assert.equal(dollarsToCents("120.01"), 12001);
});
