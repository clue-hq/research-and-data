import test from "node:test";
import assert from "node:assert/strict";
import { createWorkspaceFixture } from "../data/workspace.fixture";
import { createV2MailFixture } from "../data/mail.fixture";
import { saveEmail } from "./workspace";
import { artifactVersion } from "./artifact-version";

test("all artifact surfaces resolve revisions from the owning email or mailer", () => {
  let state = createWorkspaceFixture();
  const mail = createV2MailFixture(), email = state.emails[0];
  const asset = state.artifacts.find((a) => a.emailId === email.id)!;
  assert.equal(artifactVersion(asset, state, mail), 1);
  state = saveEmail(state, email.id, email.revision, { body:"Updated reviewed account context" });
  assert.equal(artifactVersion(asset, state, mail), 2);
  const note = state.artifacts.find((a) => a.kind === "note")!;
  mail.mailers.find((m) => m.id === note.mailerId)!.revision = 9;
  assert.equal(artifactVersion(note, state, mail), 9);
});
