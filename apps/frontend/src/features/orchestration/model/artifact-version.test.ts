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
test("a recipient page keeps its own version when the linked note changes", () => {
 const data=createWorkspaceFixture(6),mail=createV2MailFixture();
 const page={...data.artifacts.find(a=>a.kind==="page")!,mailerId:mail.mailers[0].id};
 mail.mailers[0].revision=18;
 assert.equal(artifactVersion(page,mail),page.version);
});
