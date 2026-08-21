import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";
import type { Node, Scene } from "../engine/scene/contracts";
import {
  HARVESTED_AD_PAGE,
  adAutoLayout,
  adFrame,
  adGroup,
  adImage,
  adRect,
  adTokenText,
} from "./__fixtures__/scene-nodes";
import {
  GENERATED_LABEL_LENGTH,
  IMAGE_LONG_EDGE,
  REMOVE_BACKGROUND_INSTRUCTION,
  sceneGeneratedAssetLabel,
  sceneGenerationResolution,
  sceneImageBeforeSrc,
  sceneImageCandidateView,
  sceneImageEditSource,
  sceneImageStatusLine,
} from "./scene-image-ai";

/**
 * AD4.A step 3 (§1.3 row 2, the AI suite): the PURE decisions behind
 * generate / edit / remove-background / candidate review — the request
 * shaping and the gates, with no React and no transport.
 *
 * Every case runs against AD2.2's harvested bytes
 * (`__fixtures__/scene-nodes`, document `doc_ad22linkedinsquare00000000001`).
 * The accessors hand back LIVE references into the shared frozen scene, so a
 * case that needs a different node CLONES the scene and edits exactly one
 * field.
 */

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** The harvested scene with exactly one thing changed. */
function sceneWith(change: (scene: Scene) => void): Scene {
  const scene = clone(HARVESTED_AD_PAGE);
  change(scene);
  return scene;
}

/** The harvested image with exactly one field changed. */
function heroWith(change: (node: Node) => void): Node {
  const node = clone(HARVESTED_AD_PAGE).nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  change(node);
  return node;
}

// ── The generation resolution (upstream's `frameResolution`) ────────────────

it("§1.3 Generate: the resolution is the node's own aspect at long edge 1536", () => {
  // `image_hero` is 1056x676 fixed, landscape — so the WIDTH takes the long
  // edge and the height follows the aspect: round(1536 * 676 / 1056).
  assert.deepEqual(sceneGenerationResolution(adImage()), {
    height: 983,
    width: IMAGE_LONG_EDGE,
  });
});

it("§1.3 Generate: a PORTRAIT node puts the long edge on the height", () => {
  const portrait = heroWith((node) => {
    node.size = {
      height: { kind: "fixed", value: 1056 },
      width: { kind: "fixed", value: 676 },
    };
  });
  assert.deepEqual(sceneGenerationResolution(portrait), {
    height: IMAGE_LONG_EDGE,
    width: 983,
  });
});

it("§1.3 Generate: a SQUARE node is square at the long edge", () => {
  // The harvested artboard is 1200x1200 — the `width >= height` branch's
  // boundary, and the one real square in the document.
  assert.deepEqual(sceneGenerationResolution(adFrame()), {
    height: IMAGE_LONG_EDGE,
    width: IMAGE_LONG_EDGE,
  });
});

it("§1.3 Generate: a node whose size is not FIXED on both axes states no resolution", () => {
  // `computed` is null on every stored node (the harvest's own header says so),
  // so a hug height or a fill width leaves the request without a size — and
  // upstream then simply omits width/height rather than inventing one.
  assert.equal(
    sceneGenerationResolution(adAutoLayout()),
    undefined,
    "a hug height has no number to send",
  );
  assert.equal(
    sceneGenerationResolution(adGroup()),
    undefined,
    "a fill width has no number to send",
  );
});

it("§1.3 Generate: a COMPUTED layout box outranks the declared size", () => {
  // Upstream reads `computed.layout_bounds` first — the solved geometry is what
  // the picture will actually occupy. Nothing in the stored document carries
  // one, so this is the relaid-scene case the canvas mirrors up.
  const relaid = heroWith((node) => {
    node.computed = {
      layout_bounds: { height: 200, width: 400, x: 0, y: 0 },
      render_bounds: { height: 200, width: 400, x: 0, y: 0 },
    };
  });
  assert.deepEqual(sceneGenerationResolution(relaid), {
    height: 768,
    width: IMAGE_LONG_EDGE,
  });
});

it("§1.3 Generate: a zero or negative box states no resolution rather than a 0-pixel request", () => {
  const collapsed = heroWith((node) => {
    node.size = {
      height: { kind: "fixed", value: 0 },
      width: { kind: "fixed", value: 1056 },
    };
  });
  assert.equal(sceneGenerationResolution(collapsed), undefined);
});

// ── The asset label (upstream's `prompt.slice(0, 60)`) ─────────────────────

it("§1.3 Generate: the asset label is the trimmed prompt, cut at 60 characters", () => {
  assert.equal(sceneGeneratedAssetLabel("  a calm clinic reception  "), "a calm clinic reception");
  const long = "x".repeat(120);
  assert.equal(sceneGeneratedAssetLabel(long).length, GENERATED_LABEL_LENGTH);
  assert.equal(sceneGeneratedAssetLabel(long), "x".repeat(GENERATED_LABEL_LENGTH));
});

// ── The edit gate (upstream's `canEdit`) ───────────────────────────────────

it("§1.3 Edit: the source is the node's own asset when it is a ready image", () => {
  assert.equal(
    sceneImageEditSource(adImage(), HARVESTED_AD_PAGE),
    "asset_ing_2b0928ca4f3a3c70",
  );
});

it("§1.3 Edit: a non-image selection has no source at all", () => {
  assert.equal(sceneImageEditSource(adTokenText(), HARVESTED_AD_PAGE), null);
  assert.equal(sceneImageEditSource(adRect(), HARVESTED_AD_PAGE), null);
});

it("§4: a LOCKED image offers no edit — a candidate it could never accept is a half write", () => {
  assert.equal(
    sceneImageEditSource(
      heroWith((node) => {
        node.locked = true;
      }),
      HARVESTED_AD_PAGE,
    ),
    null,
  );
});

it("§1.3 Edit: an asset that is not READY offers no edit — there are no pixels to edit", () => {
  for (const status of ["pending", "failed", "archived"] as const) {
    const scene = sceneWith((next) => {
      next.assets.asset_ing_2b0928ca4f3a3c70.status = status;
    });
    assert.equal(
      sceneImageEditSource(scene.nodes.image_hero, scene),
      null,
      `an asset with status ${status} is not editable`,
    );
  }
});

it("§1.3 Edit: an asset the SCENE does not carry is treated as ready — upstream's own default", () => {
  // `(asset?.status ?? "ready") === "ready"`: the scene's asset map is not the
  // registry, so an unknown record is not evidence of a broken one.
  const scene = sceneWith((next) => {
    delete next.assets.asset_ing_2b0928ca4f3a3c70;
  });
  assert.equal(
    sceneImageEditSource(scene.nodes.image_hero, scene),
    "asset_ing_2b0928ca4f3a3c70",
  );
});

it("§1.3 Edit: an image node with no asset id at all offers no edit", () => {
  const empty = heroWith((node) => {
    if (node.kind.kind === "image") node.kind.asset_id = "";
  });
  assert.equal(sceneImageEditSource(empty, HARVESTED_AD_PAGE), null);
});

// ── The candidate's presentation view ──────────────────────────────────────

it("§1.3 Review: the candidate resolves through the PUBLIC content-addressed passthrough", () => {
  const digest = "a".repeat(64);
  const view = sceneImageCandidateView({
    id: "asset_gen_1",
    kind: "raster_image",
    label: "a calm clinic reception",
    media: { digest: { algorithm: "sha256", value: digest } },
    source: { kind: "generated", model: "image-gen-v1", request_id: null },
    status: "ready",
  });
  assert.deepEqual(view, {
    label: "a calm clinic reception",
    previewSrc: `/api/clue/design-public/asset-store/${digest}`,
  });
});

it("§1.3 Review: the candidate prefers its THUMBNAIL digest when the API stamped one", () => {
  const bytes = "b".repeat(64);
  const thumb = "c".repeat(64);
  const view = sceneImageCandidateView({
    id: "asset_gen_2",
    kind: "raster_image",
    label: "edited",
    media: {
      digest: { algorithm: "sha256", value: bytes },
      thumbnail: {
        digest: { algorithm: "sha256", value: thumb },
        location: {
          opaque_ref: `ws/design/${thumb}`,
          provider: "clue-storage",
          url: null,
        },
        mime_type: "image/png",
      },
    },
    source: { kind: "generated", model: "image-gen-v1", request_id: null },
    status: "ready",
  });
  assert.equal(view.previewSrc, `/api/clue/design-public/asset-store/${thumb}`);
});

it("§1.3 Review: a candidate with no usable digest shows NOTHING rather than a url that can only 404", () => {
  const view = sceneImageCandidateView({
    id: "asset_gen_3",
    kind: "raster_image",
    label: "edited",
    source: { kind: "generated", model: "image-gen-v1", request_id: null },
    status: "ready",
  });
  assert.equal(view.previewSrc, null);
});

// ── The fixed remove-background instruction ────────────────────────────────

it("§1.3 Remove background: the instruction is upstream's, verbatim", () => {
  assert.equal(REMOVE_BACKGROUND_INSTRUCTION, "Remove the background completely");
});

// ── The asset status line ──────────────────────────────────────────────────

it("§1.3 Status: a READY asset says nothing — the Fill thumbnail above IS the statement", () => {
  assert.equal(sceneImageStatusLine(adImage(), HARVESTED_AD_PAGE), null);
});

it("§1.3 Status: a NOT-ready asset names itself and its status — upstream's own line", () => {
  const scene = sceneWith((next) => {
    next.assets.asset_ing_2b0928ca4f3a3c70.status = "pending";
  });
  assert.equal(
    sceneImageStatusLine(scene.nodes.image_hero, scene),
    "Asset asset_ing_2b0928ca4f3a3c70 · pending",
  );
});

it("§1.3 Status: an image node carrying no asset at all says so", () => {
  const empty = heroWith((node) => {
    if (node.kind.kind === "image") node.kind.asset_id = "";
  });
  assert.equal(sceneImageStatusLine(empty, HARVESTED_AD_PAGE), "No image yet");
});

it("§1.3 Status: a NON-image node says nothing — the row is image-only", () => {
  assert.equal(sceneImageStatusLine(adTokenText(), HARVESTED_AD_PAGE), null);
  assert.equal(sceneImageStatusLine(adRect(), HARVESTED_AD_PAGE), null);
});

// ══ The composition rule, pinned against the panel's own source ═════════════
//
// A `.tsx` cannot be imported under this runner (`tsx --test`, no DOM), so the
// bindings below are pinned against the literal source — the technique this
// lane already uses for the SIZE_PRESETS vocabulary and the A26–A31 component
// rulings. Rendering itself stays browser-provable.

const AD_INSPECTOR_SOURCE = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../../chat-shell/components/image-inspector.tsx",
  ),
  "utf8",
);

const CHAT_SHELL_STYLESHEET = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../../chat-shell/components/chat-shell.module.css",
  ),
  "utf8",
);

/** The EXACT set of classes the three AI components are allowed to name — the
 * category-2 and category-3 entries of this slice's composition enumeration,
 * and nothing else. An allowlist rather than an exists-in-the-stylesheet check,
 * because the weaker form passes the moment somebody adds a rule AND uses it,
 * which is precisely the move the phase's never-invent-UI law forbids. Growing
 * this list is a deliberate act with a reviewer attached. */
const AI_SUITE_ALLOWED_CLASSES = [
  "fieldGrid",
  "imageReplaceField",
  "inspectorStatusNote",
  "sharePrimaryButtonWide",
  "shareSecondaryButton",
];

it("THE COMPOSITION RULE: the AI suite names ONLY the classes its enumeration justified", () => {
  // The single most important rule in this phase: the dummy UI is presentation
  // truth and ceiling. The AI suite is the first surface the dummy designed
  // none of, so this guard makes "no new CSS" mechanical rather than a promise.
  const bodies = ["AdImageAiRows", "AdImageCandidateReview", "AdImageReviewTile"]
    .map((name) => {
      const body = new RegExp(`function ${name}\\([\\s\\S]*?\\n}\\n`).exec(
        AD_INSPECTOR_SOURCE,
      );
      assert.ok(body, `image-inspector.tsx no longer defines ${name}`);
      return body[0];
    })
    .join("\n");
  const used = [
    ...new Set(
      [...bodies.matchAll(/\bstyles\.([A-Za-z0-9_]+)/g)].map((match) => match[1]),
    ),
  ].sort();
  assert.deepEqual(
    used,
    AI_SUITE_ALLOWED_CLASSES,
    "the AI suite names a class its enumeration did not justify (or stopped using one)",
  );
});

it("THE COMPOSITION RULE: every class the whole ad panel names already exists in the stylesheet", () => {
  // The weaker, wider guard — it cannot catch an invented class that was also
  // authored, which the allowlist above does, but it does catch a typo or a
  // member deleted out from under the panel across all seven schemas.
  const used = new Set(
    [...AD_INSPECTOR_SOURCE.matchAll(/\bstyles\.([A-Za-z0-9_]+)/g)].map(
      (match) => match[1],
    ),
  );
  assert.ok(used.size > 0, "no css-module members found — the regex has rotted");
  // Anywhere in the sheet, not anchored to a line start: some of the panel's
  // classes are authored only as descendants (`.alignmentControl
  // .alignmentActive`), which is still a class the stylesheet defines.
  const missing = [...used].filter(
    (name) =>
      !new RegExp(`\\.${name}(?![A-Za-z0-9_-])`).test(CHAT_SHELL_STYLESHEET),
  );
  assert.deepEqual(missing, [], "classes the stylesheet does not define");
});

it("THE COMPOSITION RULE: the AI rows carry no inline style and no new icon", () => {
  const rows = /function AdImageAiRows\([\s\S]*?\n}\n/.exec(AD_INSPECTOR_SOURCE);
  assert.ok(rows, "image-inspector.tsx no longer defines AdImageAiRows");
  const review = /function AdImageCandidateReview\([\s\S]*?\n}\n/.exec(
    AD_INSPECTOR_SOURCE,
  );
  assert.ok(review, "image-inspector.tsx no longer defines AdImageCandidateReview");
  for (const [name, body] of [
    ["AdImageAiRows", rows[0]],
    ["AdImageCandidateReview", review[0]],
  ] as const) {
    assert.ok(!body.includes("style={"), `${name} carries an inline style`);
    assert.ok(
      !/<InspectorIcon/.test(body),
      `${name} introduces an inspector icon upstream's own buttons do not justify`,
    );
  }
});

it("§1.3 Alt text: the box COMMITS on blur/Enter, never per keystroke", () => {
  // The first of the five disciplines this lane paid for in blood: a
  // per-keystroke description would persist one document version and one undo
  // step per letter typed.
  const field = /<InspectorInput\s+ariaLabel="Image alt text"[\s\S]*?\/>/.exec(
    AD_INSPECTOR_SOURCE,
  );
  assert.ok(field, "image-inspector.tsx no longer renders the alt-text field");
  assert.match(field[0], /onCommit=\{commitAltText\}/);
  assert.ok(
    !/onChange=\{\(value\) => setValue\("altText"/.test(field[0]),
    "the keystroke handler must draft locally, never dispatch",
  );
});

it("§4 / A29: the alt-text commit records NOTHING against a locked node", () => {
  const commit = /const commitAltText = \(\) => \{[\s\S]*?\n  \};/.exec(
    AD_INSPECTOR_SOURCE,
  );
  assert.ok(commit, "image-inspector.tsx no longer defines commitAltText");
  assert.match(commit[0], /if \(locked\) return;/);
  // And a write that changes nothing is not a write — compared against what
  // this panel believes the document holds, never against the live prop.
  assert.match(commit[0], /altText\.draft !== altText\.committed/);
});

it("§1.3: the alt-text box re-seeds from the LIVE document, so a Replace cannot leave it stale", () => {
  // Replace image overwrites `asset_placement.alt_text` with the new asset's
  // label, so without this the box would go on describing the picture that just
  // left — a control displaying a value the document does not have.
  assert.match(
    AD_INSPECTOR_SOURCE,
    /const documentAltText = hydrated\?\.altText \?\? state\.altText;/,
  );
  // REVIEW FIX: the re-seed fires against `seen` — the last hydrated value this
  // component reacted to — and NOT against the record the commit just moved.
  // The optimistic apply mirrors up through a passive effect, so for a render
  // or two after a commit the live prop still holds the PRE-write text;
  // comparing against the record would fire the re-seed against that stale
  // value and flash the old description back into the box.
  assert.match(AD_INSPECTOR_SOURCE, /if \(altText\.seen !== documentAltText\) \{/);
  assert.ok(
    !/altText\.committed !== documentAltText/.test(AD_INSPECTOR_SOURCE),
    "the re-seed must not compare the panel's record against the live prop",
  );
});

it("REVIEW: the candidate review is a SIBLING of the edit block, so a lock cannot vanish it", () => {
  // `canEdit` folds in §4's lock, so nesting the review inside it removed
  // Before/After, Accept, Reject and Save-as-new the moment the header lock was
  // clicked — a paid result taken off the screen with nothing to say where it
  // went. Upstream renders the two as siblings for this exact reason.
  const rows = /function AdImageAiRows\([\s\S]*?\n}\n/.exec(AD_INSPECTOR_SOURCE);
  assert.ok(rows, "image-inspector.tsx no longer defines AdImageAiRows");
  const canEditBlock = rows[0].slice(
    rows[0].indexOf("{canEdit ? ("),
    rows[0].indexOf("{candidate ? ("),
  );
  assert.ok(
    canEditBlock.length > 0,
    "the canEdit block no longer precedes the review",
  );
  assert.ok(
    !canEditBlock.includes("AdImageCandidateReview"),
    "the review must not be nested inside the canEdit block",
  );
  assert.match(rows[0], /\{candidate \? \(\s*<AdImageCandidateReview/);
});

it("REVIEW: Accept and Save as new clear the instruction; Reject deliberately keeps it", () => {
  const review = /function AdImageCandidateReview\([\s\S]*?\n}\n/.exec(
    AD_INSPECTOR_SOURCE,
  );
  assert.ok(review, "image-inspector.tsx no longer defines AdImageCandidateReview");
  const clears = review[0].match(/onClearInstruction\(\);/g) ?? [];
  assert.equal(clears.length, 2, "exactly Accept and Save as new clear it");
  const rejectButton = review[0].slice(review[0].indexOf("onRejectCandidate"));
  assert.ok(
    !rejectButton.slice(0, 120).includes("onClearInstruction"),
    "Reject keeps the instruction — trying again, adjusted, is the point of rejecting",
  );
});

it("§1.3: the two spend buttons are DISABLED with nothing typed and while one is in flight", () => {
  const rows = /function AdImageAiRows\([\s\S]*?\n}\n/.exec(AD_INSPECTOR_SOURCE);
  assert.ok(rows, "image-inspector.tsx no longer defines AdImageAiRows");
  assert.match(rows[0], /disabled=\{generating \|\| prompt\.trim\(\) === ""\}/);
  assert.match(rows[0], /disabled=\{instruction\.trim\(\) === ""\}/);
  // The pending label is the status, on the one button class in this shell
  // with an authored disabled treatment.
  assert.match(rows[0], /\{generating \? "Generating…"/);
  assert.match(rows[0], /Applying edit…/);
});

// ── The Before half of the review ──────────────────────────────────────────

it("§1.3 Review: Before is the node's OWN asset, through the public passthrough", () => {
  assert.equal(
    sceneImageBeforeSrc(adImage(), HARVESTED_AD_PAGE),
    "/api/clue/design-public/asset-store/2b0928ca4f3a3c70c5c2fed22996f0428da219c953a14e71567b73c1d8af937a",
  );
});

it("§1.3 Review: Before shows NOTHING rather than the dummy's stock photograph", () => {
  // A stranger's picture captioned "Before" is not a wrong thumbnail, it is a
  // wrong ANSWER to the question the review panel is asking — so an
  // unresolvable asset resolves to null and the tile stays empty.
  const scene = sceneWith((next) => {
    delete next.assets.asset_ing_2b0928ca4f3a3c70.media;
  });
  assert.equal(sceneImageBeforeSrc(scene.nodes.image_hero, scene), null);
  assert.equal(sceneImageBeforeSrc(adTokenText(), HARVESTED_AD_PAGE), null);
});

it("§1.3 Review: BOTH tiles render, captioned Before and After (the ruling of 2026-08-21)", () => {
  // §1.3's row names the control — "Before/After candidate review" — and a
  // comparison whose two halves are separated by two form fields is a candidate
  // preview beside a coincidence. The leaner one-tile reading (the Fill
  // thumbnail two rows up IS the before) was considered and overruled.
  const review = /function AdImageCandidateReview\([\s\S]*?\n}\n/.exec(
    AD_INSPECTOR_SOURCE,
  );
  assert.ok(review, "image-inspector.tsx no longer defines AdImageCandidateReview");
  assert.match(review[0], /caption="Before" src=\{imageAi\.beforeSrc\}/);
  assert.match(review[0], /caption="After" src=\{candidate\.previewSrc\}/);
  // Three buttons, but never a three-column cram: `.fieldGrid` is a fixed
  // two-up, so Accept/Reject share it and Save as new runs full width beneath.
  const grids = review[0].match(/styles\.fieldGrid/g) ?? [];
  assert.equal(grids.length, 2, "one grid for the tiles, one for the button pair");
  assert.match(review[0], /Save as new/);
});

it("REVIEW: the AI rows are OFFERED only when there is a real document to write to", () => {
  // Both ad call sites pass `imageAi` unconditionally and the hook always
  // returns a binding, so without this gate the rows render on the pre-load
  // path — including the fixture layer tree's "Image" row, which opens this
  // schema before any scene exists — as a live-looking Generate button whose
  // every click is refused in silence. That is this lane's signature defect.
  const session = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../hooks/use-scene-editing-session.ts",
    ),
    "utf8",
  );
  assert.match(
    session,
    /const imageAi = activeDocumentId && scene \? imageAiBinding : undefined;/,
  );
  // And the panel still treats an absent binding as "render nothing".
  assert.match(AD_INSPECTOR_SOURCE, /\{imageAi \? <AdImageAiRows imageAi=\{imageAi\} \/> : null\}/);
});
