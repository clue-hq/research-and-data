import assert from "node:assert/strict";
import test from "node:test";
import { composerAction, hasComposerDraft } from "./composer-action";

const base = { running: false, stopping: false, hasDraft: false, disabled: false, sendDisabled: false, submitting: false };

test("composer switches between Send and Stop without losing the pending Stop", () => {
  assert.deepEqual(composerAction(base), { kind: "send", disabled: true });
  assert.deepEqual(composerAction({ ...base, hasDraft: true }), { kind: "send", disabled: false });
  assert.deepEqual(composerAction({ ...base, running: true }), { kind: "stop", disabled: false });
  assert.deepEqual(composerAction({ ...base, running: true, hasDraft: true }), { kind: "send", disabled: false });
  for (const hasDraft of [false, true]) {
    assert.deepEqual(composerAction({ ...base, running: true, stopping: true, hasDraft }), { kind: "stop", disabled: true });
  }
  assert.deepEqual(composerAction({ ...base, running: true, sendDisabled: true }), { kind: "stop", disabled: false });
  assert.deepEqual(composerAction({ ...base, hasDraft: true, sendDisabled: true }), { kind: "send", disabled: true });
});

test("draft validity ignores empty editor markers and accepts references or ready attachments", () => {
  assert.equal(hasComposerDraft(" \n\u200B\uFEFF ", [], []), false);
  assert.equal(hasComposerDraft("", ["account-id"], []), true);
  const file = { id: "file", filename: "brief.pdf", type: "file" as const, url: "", mediaType: "application/pdf" };
  assert.equal(hasComposerDraft("", [], [{ ...file, status: "ready" }]), true);
  assert.equal(hasComposerDraft("", [], [{ ...file, status: "uploading" }]), false);
  assert.equal(hasComposerDraft("", [], [{ ...file, status: "failed" }]), false);
});
