import assert from "node:assert/strict";
import test from "node:test";
import type { ProjectComposerAttachment } from "./project-composer";
import {
  attachmentFamily,
  attachmentLimitError,
  chatAttachmentSnapshot,
  CHAT_ATTACHMENT_LIMITS,
} from "./chat-attachments";

function ready(
  i: number,
  extra: Partial<ProjectComposerAttachment> = {},
): ProjectComposerAttachment {
  return {
    id: `a${i}`,
    filename: `f${i}.md`,
    mediaType: "text/markdown",
    status: "ready",
    type: "file",
    url: "",
    uploadId: `u${i}`,
    artifactKey: `ws/${"a".repeat(64)}`,
    sha256: "a".repeat(64),
    byteCount: 10,
    ...extra,
  };
}

test("family by type then by extension", () => {
  assert.equal(attachmentFamily({ name: "x.md", type: "" }), "text");
  assert.equal(attachmentFamily({ name: "x.txt", type: "text/plain" }), "text");
  assert.equal(attachmentFamily({ name: "x.png", type: "image/png" }), "image");
  assert.equal(attachmentFamily({ name: "x.pdf", type: "application/pdf" }), null);
});

test("limits: count, per-file size, total size", () => {
  const big = {
    name: "b.png",
    type: "image/png",
    size: CHAT_ATTACHMENT_LIMITS.imageMaxBytes + 1,
  } as File;
  assert.match(attachmentLimitError([], [big]) ?? "", /10 MB/);
  const many = Array.from(
    { length: 11 },
    (_, i) => ({ name: `f${i}.md`, type: "text/markdown", size: 1 }) as File,
  );
  assert.match(attachmentLimitError([], many) ?? "", /ten files/);
  assert.equal(
    attachmentLimitError([], [{ name: "ok.md", type: "text/markdown", size: 1 } as File]),
    null,
  );
});

test("snapshot is null until every attachment is ready", () => {
  assert.equal(
    chatAttachmentSnapshot([ready(1), { ...ready(2), status: "uploading" }]),
    null,
  );
  const snap = chatAttachmentSnapshot([ready(1)]);
  assert.deepEqual(snap, [
    {
      uploadId: "u1",
      artifactKey: `ws/${"a".repeat(64)}`,
      sha256: "a".repeat(64),
      mediaType: "text/markdown",
      byteCount: 10,
      filename: "f1.md",
    },
  ]);
});
