import { test } from "node:test";
import assert from "node:assert/strict";
import { createV2MailFixture } from "../../orchestration/data/mail.fixture";
import { withWalkthroughMail, WALKTHROUGH_CAMPAIGN } from "../data/walkthrough.fixture";
import { approveMailers, readiness, reviewMailer } from "../../direct-mail/model/direct-mail";
import { updateOutreachPage, reviewOutreachPage } from "../../direct-mail/model/outreach-page";

test("500 accounts share one recipient model and repeated seeding preserves edits", () => {
  const state = withWalkthroughMail(createV2MailFixture());
  const rows = state.mailers.filter(m => m.campaignId === WALKTHROUGH_CAMPAIGN);
  assert.equal(new Set(rows.map(m => m.accountId)).size, 500);
  assert.equal(rows.length, 1000);
  assert.equal(rows.filter(m => m.accountId === "snowflake").length, 2);
  rows[0].note = "My edited note";
  assert.equal(withWalkthroughMail(state).mailers.find(m => m.id === rows[0].id)?.note, "My edited note");
  assert.equal(state.pages?.length, 1000);
});

test("page review is version-bound and approval pins the rendered page", () => {
  let state = withWalkthroughMail(createV2MailFixture());
  const id = "walkthrough-snowflake-morgan";
  let m = state.mailers.find(m => m.id === id)!;
  const page = state.pages!.find(p => p.id === m.pageId)!;
  assert.ok(readiness(m, state).some(i => i.includes("landing page")));
  state = reviewOutreachPage(state, page.id, page.version);
  m = state.mailers.find(m => m.id === id)!;
  assert.deepEqual(readiness(m, state), []);
  state = reviewMailer(state, id, m.revision);
  state = updateOutreachPage(state, page.id, page.version, { headline: "Updated account plan" });
  m = state.mailers.find(m => m.id === id)!;
  assert.equal(m.stage, "needs_review");
  assert.equal(state.pages!.find(p => p.id === page.id)!.reviewedVersion, null);
  assert.throws(() => reviewOutreachPage(state, page.id, page.version), /changed/);
  state = reviewOutreachPage(state, page.id, page.version + 1);
  m = state.mailers.find(m => m.id === id)!;
  state = reviewMailer(state, id, m.revision);
  m = state.mailers.find(m => m.id === id)!;
  const result = approveMailers(state, [{ id, revision: m.revision }]);
  assert.equal(result.results[0].ok, true);
  assert.equal(result.state.mailers.find(m => m.id === id)!.approval!.page?.headline, "Updated account plan");
  assert.throws(() => updateOutreachPage(result.state, page.id, page.version + 1, { body: "Changed" }), /approved/);
});

test("shipped samples have a coherent destination and independent shipment legs", () => {
  const state = withWalkthroughMail(createV2MailFixture());
  const t = state.mailers.find(m => m.id === "walkthrough-snowflake-taylor")!;
  assert.equal(t.stage, "shipped");
  assert.equal(t.qr?.destinationStatus, "published");
  assert.ok(t.qr?.verifiedAt);
  assert.equal(state.pages!.find(p => p.id === t.pageId)?.publication, "published");
  assert.notEqual(t.inbound?.trackingNumber, t.outbound?.trackingNumber);
});
