import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

/**
 * Spec 2026-10-30 §3.8: every file a person attaches goes up as a chat
 * attachment, whatever the panel shows; the server decides how it reaches the
 * agent. The composer used to send an image as a design reference when an ad
 * was the item open in the panel, and as a chat attachment otherwise — so the
 * same image reached the agent or vanished depending on the panel.
 */
const source = readFileSync(
  new URL("./chat-surface.tsx", import.meta.url),
  "utf8",
);

test("the composer has one attachment intake, the chat attachment", () => {
  assert.doesNotMatch(source, /useDesignReferenceAttachments/);
  assert.doesNotMatch(source, /routeAttachmentFiles/);
  assert.doesNotMatch(source, /designReferencesEnabled/);
  assert.match(source, /onFiles: chatAttachments\.onFiles/);
  assert.match(
    source,
    /onAttachmentFiles=\{[\s\S]{0,120}chatAttachments\.onFiles/,
  );
});
