import test from "node:test";
import assert from "node:assert/strict";
import { createV2MailFixture } from "./mail.fixture";
import { createWorkspaceFixture } from "./workspace.fixture";
import { approveMailers, estimate, readiness, reviewMailer } from "@/features/direct-mail/model/direct-mail";

test("V2 mailers join exactly to their account and contact across all surfaces", () => {
  const mail = createV2MailFixture(), workspace = createWorkspaceFixture();
  assert.equal(mail.mailers.length, 4);
  for (const m of mail.mailers) {
    const account = workspace.accounts.find((a) => a.mailerId === m.id)!;
    assert.ok(account);
    assert.equal(m.accountId, account.id);
    assert.equal(m.contactId, account.contactId);
    assert.equal(m.projectId, workspace.project.id);
    assert.equal(m.signature, `${workspace.people.find((p) => p.id === account.senderId)!.name}\nClue`);
    if (m.approval) assert.equal(m.approval.estimatedCents, estimate(m));
  }
});
test("V2 can review and approve Avery without losing the address hold for Priya", () => {
  const state = createV2MailFixture(), avery = state.mailers.find((m) => m.id === "mailer-avery")!;
  assert.deepEqual(readiness(avery, state), []);
  const reviewed = reviewMailer(state, avery.id, avery.revision);
  const ready = reviewed.mailers.find((m) => m.id === avery.id)!;
  const result = approveMailers(reviewed, [{ id: ready.id, revision: ready.revision }]);
  assert.equal(result.results[0].ok, true);
  assert.equal(result.state.mailers.find((m) => m.id === avery.id)?.stage, "approved");
  assert.ok(readiness(state.mailers.find((m) => m.id === "mailer-priya")!, state).some((issue) => /address/i.test(issue)));
  assert.equal(state.creditEntries?.length, 2);
  assert.equal(result.state.creditEntries?.length, 3);
});
