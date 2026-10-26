import test from "node:test";
import assert from "node:assert/strict";
import { createWorkspaceFixture } from "../data/workspace.fixture";
import { approveEmail, saveEmail, setAccountOwner, markReplyHandled, validateWorkspaceLinks, workspaceMetrics } from "./workspace";
test("account plan includes email-led accounts without a mailer and canonical asset references", () => {
  const state = createWorkspaceFixture();
  assert.ok(state.accounts.some((a) => a.approach === "Email-led" && a.mailerId === null));
  assert.deepEqual(validateWorkspaceLinks(state), []);
  state.artifacts[0].accountId = "missing";
  assert.ok(validateWorkspaceLinks(state).length > 0);
});
test("owner assignment preserves sender and refuses stale or unknown assignments", () => {
  const state = createWorkspaceFixture(), account = state.accounts[0];
  const changed = setAccountOwner(state, account.id, account.revision, "jamie");
  assert.equal(changed.accounts[0].ownerId, "jamie");
  assert.equal(changed.accounts[0].senderId, account.senderId);
  assert.equal(state.accounts[0].ownerId, "alex");
  assert.throws(() => setAccountOwner(changed, account.id, account.revision, "alex"), /changed/);
  assert.throws(() => setAccountOwner(state, account.id, account.revision, "unknown"), /owner/);
});
test("email approval snapshots recipient-ready content and editing invalidates it", () => {
  const state = createWorkspaceFixture(), email = state.emails.find((e) => e.id === "email-meridian")!;
  const approved = approveEmail(state, email.id, email.revision);
  const current = approved.emails.find((e) => e.id === email.id)!;
  assert.equal(current.status, "scheduled");
  assert.equal(current.approval?.body, email.body);
  const edited = saveEmail(approved, email.id, current.revision, { body: "A useful revised message", senderId: "alex" });
  assert.equal(edited.emails.find((e) => e.id === email.id)?.approval, null);
  assert.equal(edited.emails.find((e) => e.id === email.id)?.status, "draft");
  assert.throws(() => approveEmail(edited, email.id, email.revision), /changed/);
});
test("email refuses blank copy, unresolved templates, invalid sender and missing records", () => {
  const state = createWorkspaceFixture(), email = state.emails[0];
  assert.throws(() => saveEmail(state, email.id, email.revision, { body: " " }), /message/);
  assert.throws(() => saveEmail(state, email.id, email.revision, { senderId: "maya" }), /sender/);
  const updated = saveEmail(state, email.id, email.revision, { body: "Hi {{first_name}}" });
  assert.throws(() => approveEmail(updated, email.id, email.revision + 1), /template/);
  assert.throws(() => approveEmail(state, "missing", 1), /available/);
});
test("human reply stops the sequence and resolving it never restarts or sends", () => {
  const state = createWorkspaceFixture(), email = state.emails.find((e) => e.status === "reply")!;
  assert.equal(email.sequenceStopped, true);
  assert.throws(() => approveEmail(state, email.id, email.revision), /reply/);
  const next = markReplyHandled(state, email.id, email.revision);
  assert.equal(next.emails.find((e) => e.id === email.id)?.status, "handled");
  assert.equal(next.emails.find((e) => e.id === email.id)?.sequenceStopped, true);
});
test("metrics use distinct recorded outcomes without treating delivery as a meeting", () => {
  const state = createWorkspaceFixture();
  const metrics = workspaceMetrics(state);
  assert.equal(metrics.accounts, state.accounts.length);
  assert.equal(metrics.replies, 1);
  assert.equal(metrics.meetingsHeld, 0);
  assert.equal(metrics.opportunities, 0);
});
