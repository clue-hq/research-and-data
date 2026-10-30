import assert from "node:assert/strict";
import test from "node:test";
import type { ProjectComposerAttachment } from "./project-composer";
import {
  attachmentFamily,
  attachmentLimitError,
  chatAttachmentSnapshot,
  CHAT_ATTACHMENT_ACCEPT,
  CHAT_ATTACHMENT_LIMITS,
} from "./chat-attachments";

const DOCX =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const PPTX =
  "application/vnd.openxmlformats-officedocument.presentationml.presentation";
const XLSX =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

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
  assert.equal(
    attachmentFamily({ name: "x.pdf", type: "application/pdf" }),
    "document",
  );
  assert.equal(attachmentFamily({ name: "x.exe", type: "" }), null);
});

test("documents are their own family, by type or by extension", () => {
  assert.equal(
    attachmentFamily({ name: "x.pdf", type: "application/pdf" }),
    "document",
  );
  assert.equal(attachmentFamily({ name: "x.docx", type: DOCX }), "document");
  assert.equal(attachmentFamily({ name: "x.pptx", type: PPTX }), "document");
  assert.equal(attachmentFamily({ name: "x.xlsx", type: XLSX }), "document");
  assert.equal(
    attachmentFamily({ name: "x.csv", type: "text/csv" }),
    "document",
  );
  assert.equal(
    attachmentFamily({ name: "x.json", type: "application/json" }),
    "document",
  );
  // Browsers frequently report a generic, empty or plain wrong type for these.
  for (const name of [
    "x.pdf",
    "x.docx",
    "x.pptx",
    "x.xlsx",
    "x.csv",
    "x.json",
  ]) {
    assert.equal(attachmentFamily({ name, type: "" }), "document", name);
    assert.equal(
      attachmentFamily({ name, type: "application/octet-stream" }),
      "document",
      name,
    );
  }
  assert.equal(
    attachmentFamily({ name: "x.csv", type: "application/vnd.ms-excel" }),
    "document",
  );
});

test("the accept list offers every document type", () => {
  const accepted = CHAT_ATTACHMENT_ACCEPT.split(",");
  for (const entry of [
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".csv",
    ".json",
    "application/pdf",
    DOCX,
    PPTX,
    XLSX,
    "text/csv",
    "application/json",
  ]) {
    assert.ok(accepted.includes(entry), entry);
  }
});

test("a document may be 25 MB but not a byte more", () => {
  const pdf = (size: number) =>
    ({ name: "deck.pdf", type: "application/pdf", size }) as File;
  assert.equal(
    CHAT_ATTACHMENT_LIMITS.documentMaxBytes,
    26_214_400,
    "25 MiB, matching the backend's CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES",
  );
  assert.equal(
    attachmentLimitError([], [pdf(CHAT_ATTACHMENT_LIMITS.documentMaxBytes)]),
    null,
  );
  assert.equal(
    attachmentLimitError(
      [],
      [pdf(CHAT_ATTACHMENT_LIMITS.documentMaxBytes + 1)],
    ),
    "deck.pdf is over 25 MB.",
  );
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
    attachmentLimitError(
      [],
      [{ name: "ok.md", type: "text/markdown", size: 1 } as File],
    ),
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

test("SVG, HEIC, AVIF, TIFF, BMP and ICO are chat images (spec 2026-10-30)", () => {
  for (const [name, type] of [
    ["logo.svg", "image/svg+xml"],
    ["photo.heic", ""],
    ["photo.HEIF", ""],
    ["hero.avif", "image/avif"],
    ["scan.tif", ""],
    ["scan.tiff", "image/tiff"],
    ["old.bmp", "image/bmp"],
    ["favicon.ico", "image/x-icon"],
  ] as const) {
    assert.equal(attachmentFamily({ name, type }), "image", name);
  }
  for (const accepted of [
    ".svg",
    ".heic",
    ".heif",
    ".avif",
    ".tif",
    ".tiff",
    ".bmp",
    ".ico",
  ]) {
    assert.ok(CHAT_ATTACHMENT_ACCEPT.split(",").includes(accepted), accepted);
  }
});
