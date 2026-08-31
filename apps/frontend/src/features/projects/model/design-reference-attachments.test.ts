import assert from "node:assert/strict";
import test from "node:test";
import type { ProjectComposerAttachment } from "./project-composer";
import {
  designReferenceContextSnapshot,
  isDesignReferenceMediaType,
  MAX_DESIGN_REFERENCE_ATTACHMENTS,
} from "./design-reference-attachments";

function attachment(
  index: number,
  status: ProjectComposerAttachment["status"] = "ready",
): ProjectComposerAttachment {
  return {
    assetId: status === "ready" ? `asset_${index}` : undefined,
    filename: `reference-${index}.png`,
    id: `local-${index}`,
    mediaType: "image/png",
    status,
    type: "file",
    url: `blob:reference-${index}`,
  };
}

test("reference image media types are an exact image-only allowlist", () => {
  for (const mediaType of [
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/svg+xml",
  ]) {
    assert.equal(isDesignReferenceMediaType(mediaType), true);
  }
  assert.equal(isDesignReferenceMediaType("application/pdf"), false);
  assert.equal(isDesignReferenceMediaType("image/gif"), false);
});

test("zero, one, and four ready references snapshot in visible order", () => {
  assert.deepEqual(designReferenceContextSnapshot([]), []);
  assert.deepEqual(designReferenceContextSnapshot([attachment(0)]), [
    { objectId: "asset_0", objectType: "design_asset", version: null },
  ]);
  const four = Array.from(
    { length: MAX_DESIGN_REFERENCE_ATTACHMENTS },
    (_, index) => attachment(index),
  );
  assert.deepEqual(
    designReferenceContextSnapshot(four)?.map((ref) => ref.objectId),
    ["asset_0", "asset_1", "asset_2", "asset_3"],
  );
});

test("uploading and failed references cannot enter a queued turn", () => {
  assert.equal(designReferenceContextSnapshot([attachment(0, "uploading")]), null);
  assert.equal(designReferenceContextSnapshot([attachment(0, "failed")]), null);
});
