import test from "node:test";
import assert from "node:assert/strict";
import { createWorkspaceFixture } from "../data/workspace.fixture";
import { createV2MailFixture } from "../data/mail.fixture";
import { artifactVersion } from "./artifact-version";
test("note previews read the canonical mailer revision", () => {
  const data = createWorkspaceFixture(6),mail = createV2MailFixture();
  const note = data.artifacts.find((a) => a.kind === "note")!;
  mail.mailers.find((m) => m.id === note.mailerId)!.revision = 9;
  assert.equal(artifactVersion(note,mail),9);
});
