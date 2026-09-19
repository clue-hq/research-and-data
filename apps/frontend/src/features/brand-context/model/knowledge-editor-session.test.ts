import assert from "node:assert/strict";
import test from "node:test";
import { acceptKnowledgeDocument, acceptKnowledgeSave, changeKnowledgeBody, discardKnowledgeDraft, knowledgeSession, knowledgeSessionDirty } from "./knowledge-editor-session";

const original = { id: "v1", version: 1, path: "company/overview.md", folderId: "company", body: "\n# Original\n", name: "Overview", updatedLabel: "Today", bodyLoaded: true };
const newer = { ...original, id: "v2", version: 2, body: "# Newer server copy" };

test("opening and repeated refreshes preserve the clean session and editor history", () => {
  const session = knowledgeSession(original);
  assert.equal(knowledgeSessionDirty(session), false);
  assert.equal(acceptKnowledgeDocument(session, { ...original }), session);
  const versionOnly = acceptKnowledgeDocument(session, { ...original, id: "v2", version: 2 });
  assert.equal(versionOnly.resetKey, session.resetKey);
  assert.equal(versionOnly.base.version, 2);
});

test("clean external content changes reset the editor exactly once", () => {
  const accepted = acceptKnowledgeDocument(knowledgeSession(original), newer);
  assert.equal(accepted.body, newer.body);
  assert.equal(accepted.resetKey, 1);
  assert.equal(acceptKnowledgeDocument(accepted, newer), accepted);
  assert.equal(acceptKnowledgeDocument(accepted, original), accepted);
});

test("a dirty draft retains its original revision when refresh finds a newer UUID", () => {
  const draft = changeKnowledgeBody(knowledgeSession(original), "# My draft");
  assert.equal(acceptKnowledgeDocument(draft, newer), draft);
  assert.equal(draft.base.version, 1);
  assert.equal(draft.base.id, "v1");
  assert.equal(draft.resetKey, 0);
  const restored = changeKnowledgeBody(draft, original.body);
  assert.equal(knowledgeSessionDirty(restored), false);
});

test("Discard is explicit, clears errors and adopts the latest document", () => {
  const draft = { ...changeKnowledgeBody(knowledgeSession(original), "# Draft"), error: "Version conflict" };
  const discarded = discardKnowledgeDraft(draft, newer);
  assert.equal(discarded.body, newer.body);
  assert.equal(discarded.base.version, 2);
  assert.equal(discarded.error, null);
  assert.equal(discarded.resetKey, 1);
  assert.equal(knowledgeSessionDirty(discarded), false);
});

test("successful saves adopt the returned ID and retain history when text is unchanged", () => {
  const draft = changeKnowledgeBody(knowledgeSession(original), newer.body);
  const saved = acceptKnowledgeSave(draft, newer, draft.body);
  assert.equal(saved.base.id, newer.id);
  assert.equal(saved.base.version, 2);
  assert.equal(saved.resetKey, draft.resetKey);
  assert.equal(knowledgeSessionDirty(saved), false);
  assert.equal(acceptKnowledgeDocument(saved, original), saved);
});

test("a save completion does not erase an edit that arrived after submission", () => {
  const lateDraft = changeKnowledgeBody(knowledgeSession(original), "# Later edit");
  const saved = acceptKnowledgeSave(lateDraft, newer, "# Submitted edit");
  assert.equal(saved.body, "# Later edit");
  assert.equal(saved.base.version, 2);
  assert.equal(knowledgeSessionDirty(saved), true);
});
