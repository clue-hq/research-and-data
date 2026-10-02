// The label ladder reads the viewer's calendar days, so "today"/"yesterday"
// depend on the runtime zone. Node runs each test file in its own process, so
// pinning UTC here makes the boundary cases deterministic without touching the
// mapper's (correct) local-day behaviour.
process.env.TZ = "UTC";

import assert from "node:assert/strict";
import test from "node:test";
import { normalizeGalleryArtifact } from "@/features/gallery/model/project-gallery";
import { ProjectArtifactSchema } from "@/features/projects/model/project-workspace";
import { DesignArtifactListItemSchema, DesignArtifactListWireSchema } from "../model/artifact";
import { editedLabelFor, toProjectArtifact } from "./gallery";

// Slice 2: the gallery feed's pure mapper — one listed design artifact (the
// backend's leg-derived list item, parsed by the seam) → the gallery's
// `ProjectArtifact`. Every fixture below is the real wire shape the Slice-1
// endpoint serves (`GET /api/v1/projects/{project_id}/design-artifacts`),
// including its Postgres timestamptz offsets.

const NOW = new Date("2026-08-18T12:00:00.000Z");

function listItem(overrides: Record<string, unknown> = {}) {
  return DesignArtifactListItemSchema.parse({
    id: "doc-web-1",
    projectId: "prj-1",
    documentId: "doc-web-1",
    kind: "web",
    title: "Launch landing page",
    status: "draft",
    currentVersionId: "4",
    createdAt: "2026-08-14T09:15:00+00:00",
    updatedAt: "2026-08-18T09:15:00+00:00",
    originThreadId: "thread-9",
    ...overrides,
  });
}

test("a listed design artifact maps onto the gallery's website artifact", () => {
  const artifact = toProjectArtifact(listItem(), { now: NOW });

  assert.equal(artifact.id, "doc-web-1");
  assert.equal(artifact.title, "Launch landing page");
  assert.equal(artifact.type, "website");
  // The gallery's collateral vocabulary has no "website" member; a website
  // artifact is a microsite there (the gallery's own default for the type).
  assert.equal(artifact.collateralType, "microsite");
  assert.equal(artifact.originThreadId, "thread-9");
});

test("an ad artifact maps onto a canvas artifact with no collateral type", () => {
  // AD2.1: the feed is kind-aware, so a scene document arrives as `kind: "ad"`.
  // It becomes a `canvas` artifact — the type both editor mounts reconstruct
  // `kind: "ad"` from (`source.type === "website" ? "web" : "ad"`), so the ad
  // reaches the editor with zero mount changes. `collateralType` is left ABSENT
  // rather than guessed: the document says it is an ad, never which channel.
  const artifact = toProjectArtifact(
    listItem({ id: "doc-ad-1", documentId: "doc-ad-1", kind: "ad" }),
    { now: NOW },
  );

  assert.equal(artifact.type, "canvas");
  assert.equal("collateralType" in artifact, false);
  // An ad's thumbnail is its own rendered document, addressed the same way a
  // web document's is — nothing about the artwork is kind-specific.
  assert.equal(artifact.imagePath, "/api/clue/design/documents/doc-ad-1/thumbnail?v=4");
  assert.doesNotThrow(() => ProjectArtifactSchema.parse(artifact));
});

test("a web artifact keeps its website mapping alongside ads", () => {
  const web = toProjectArtifact(listItem(), { now: NOW });
  const ad = toProjectArtifact(listItem({ id: "doc-ad-2", kind: "ad" }), { now: NOW });

  assert.deepEqual(
    [web, ad].map((artifact) => [artifact.type, artifact.collateralType]),
    [
      ["website", "microsite"],
      ["canvas", undefined],
    ],
  );
});

test("real timestamps survive as the schema's UTC instants", () => {
  const artifact = toProjectArtifact(
    listItem({
      createdAt: "2026-08-14T09:15:00.123456+00:00",
      updatedAt: "2026-08-18T09:15:00.500000+05:30",
    }),
    { now: NOW },
  );

  // Postgres timestamptz serializes with an offset; `z.string().datetime()`
  // (the gallery model's own guard) accepts only the Z form, so the mapper
  // normalizes rather than handing the gallery a value it would reject.
  assert.equal(artifact.createdAt, "2026-08-14T09:15:00.123Z");
  assert.equal(artifact.updatedAt, "2026-08-18T03:45:00.500Z");
  assert.doesNotThrow(() => ProjectArtifactSchema.parse(artifact));
});

test("a real document carries its own thumbnail and no run", () => {
  const artifact = toProjectArtifact(listItem(), { now: NOW });

  // 2026-08-31 ruling: the thumbnail is the document's own rendered PNG, keyed
  // by its current version — nothing invented, nothing stock.
  assert.equal(artifact.imagePath, "/api/clue/design/documents/doc-web-1/thumbnail?v=4");
  // No generation run exists behind a leg-derived document.
  assert.equal(artifact.originRunId, undefined);
});

test("editedLabel is derived from updated_at in the gallery's label style", () => {
  const label = (updatedAt: string) =>
    toProjectArtifact(listItem({ updatedAt }), { now: NOW }).editedLabel;

  assert.equal(label("2026-08-18T09:15:00+00:00"), "Last edited today");
  assert.equal(label("2026-08-17T23:59:00+00:00"), "Last edited yesterday");
  assert.equal(label("2026-08-16T09:15:00+00:00"), "Last edited 2 days ago");
});

test("the relative ladder spans days, weeks, months and years", () => {
  const at = (isoDay: string) => editedLabelFor(`${isoDay}T12:00:00.000Z`, NOW);

  assert.equal(at("2026-08-18"), "Last edited today");
  assert.equal(at("2026-08-17"), "Last edited yesterday");
  assert.equal(at("2026-08-12"), "Last edited 6 days ago");
  assert.equal(at("2026-08-11"), "Last edited 1 week ago");
  assert.equal(at("2026-08-04"), "Last edited 2 weeks ago");
  assert.equal(at("2026-07-19"), "Last edited 1 month ago");
  assert.equal(at("2026-05-18"), "Last edited 3 months ago");
  assert.equal(at("2025-08-18"), "Last edited 1 year ago");
  assert.equal(at("2024-08-18"), "Last edited 2 years ago");
});

test("a future updated_at still reads as today rather than a negative age", () => {
  assert.equal(
    editedLabelFor("2026-08-18T23:00:00.000Z", NOW),
    "Last edited today",
  );
});

test("an unparseable timestamp is refused, not mapped", () => {
  // The seam schema deliberately admits any non-empty string (normalizing is
  // the mapper's job), so the mapper is the boundary that must refuse. The
  // page's feed loader catches this throw and degrades to an empty feed.
  assert.throws(
    () => toProjectArtifact(listItem({ createdAt: "not-a-date" }), { now: NOW }),
    TypeError,
  );
  assert.throws(
    () => toProjectArtifact(listItem({ updatedAt: "yesterday-ish" }), { now: NOW }),
    TypeError,
  );
});

test("editedLabelFor refuses bad input the same way (never a NaN label)", () => {
  assert.throws(() => editedLabelFor("not-a-date", NOW), TypeError);
});

test("the mapped artifact survives the gallery's normalizer", () => {
  const normalized = normalizeGalleryArtifact(
    toProjectArtifact(listItem(), { now: NOW }),
  );

  assert.equal(normalized.id, "doc-web-1");
  assert.equal(normalized.collateralType, "microsite");
  assert.equal(normalized.collateralTypeLabel, "Microsite");
  // `defaultSize` fills the website size the mapper cannot know.
  assert.deepEqual(normalized.size, {
    category: "responsive",
    height: 900,
    label: "Responsive",
    width: 1440,
  });
  assert.equal(normalized.updatedAt, "2026-08-18T09:15:00.000Z");
  assert.equal(normalized.createdAt, "2026-08-14T09:15:00.000Z");
  assert.equal(normalized.lastViewedAt, "2026-08-18T09:15:00.000Z");
  // The thumbnail URL survives normalization intact, and the optional the
  // document genuinely cannot answer stays absent — nothing is invented.
  assert.equal(normalized.imagePath, "/api/clue/design/documents/doc-web-1/thumbnail?v=4");
  assert.equal(normalized.originRunId, undefined);
});

// ── G-H (founder ruling 2026-08-20) ────────────────────────────────────────
// A card states only what its document records. The old defaults called every
// design artifact a 1080x1080 "LinkedIn ad"; both facts now come from the
// document, and a document that records neither says nothing.

test("G-H: an ad carries the document's own size and its recorded channel", () => {
  const normalized = normalizeGalleryArtifact(
    toProjectArtifact(
      listItem({
        id: "doc-ad-1",
        documentId: "doc-ad-1",
        kind: "ad",
        title: "Insight Health — LinkedIn square ad",
        artifactType: "linkedin_square_ad",
        widthPx: 1200,
        heightPx: 1200,
      }),
      { now: NOW },
    ),
  );

  assert.equal(normalized.collateralType, "linkedin-ad");
  assert.equal(normalized.collateralTypeLabel, "LinkedIn ad");
  assert.deepEqual(normalized.size, {
    category: "square",
    height: 1200,
    label: "1200 × 1200",
    width: 1200,
  });
});

test("G-H: an ad whose document records no channel claims none", () => {
  const normalized = normalizeGalleryArtifact(
    toProjectArtifact(
      listItem({
        id: "doc-ad-2",
        documentId: "doc-ad-2",
        kind: "ad",
        title: "Untitled design",
        widthPx: 1080,
        heightPx: 1920,
      }),
      { now: NOW },
    ),
  );

  assert.equal(normalized.collateralType, undefined);
  assert.equal(normalized.collateralTypeLabel, "");
  // The size is still the document's own, and its category is derived.
  assert.equal(normalized.size?.label, "1080 × 1920");
  assert.equal(normalized.size?.category, "portrait");
});

test("G-H: an ad whose document records no page states no size", () => {
  const normalized = normalizeGalleryArtifact(
    toProjectArtifact(
      listItem({ id: "doc-ad-3", documentId: "doc-ad-3", kind: "ad", title: "Empty" }),
      { now: NOW },
    ),
  );

  assert.equal(normalized.size, undefined);
  assert.equal(normalized.collateralType, undefined);
});

test("genad2 Task 5 (c): a ZERO-PAGE newborn ad card is honest-empty, not hidden", () => {
  // `open_design_leg@4` births a chat-born ad with `pages: {}`, so the feed row
  // for it carries no `width_px`/`height_px` at all — the backend is already
  // honest (it reports no page rather than a default), and this pins the
  // frontend half of that: the card still appears, with its real id and title,
  // and claims NOTHING it cannot measure. A fabricated 1080x1080 (the pre-G-H
  // default) would be the gallery inventing a design that does not exist yet.
  // Its thumbnail URL is still its own document's — the route answers for a
  // zero-page document however it answers, and the card's empty frame is the
  // fallback when that artwork does not arrive.
  const artifact = toProjectArtifact(
    listItem({
      id: "doc-ad-newborn",
      documentId: "doc-ad-newborn",
      kind: "ad",
      title: "LinkedIn ad",
    }),
    { now: NOW },
  );
  const normalized = normalizeGalleryArtifact(artifact);

  assert.equal(normalized.id, "doc-ad-newborn");
  assert.equal(normalized.title, "LinkedIn ad");
  assert.equal(normalized.source.type, "canvas");
  assert.equal(normalized.size, undefined);
  assert.equal(
    normalized.imagePath,
    "/api/clue/design/documents/doc-ad-newborn/thumbnail?v=4",
  );
});

test("G-H: an unrecognised artifact type is not forced into the vocabulary", () => {
  const artifact = toProjectArtifact(
    listItem({
      id: "doc-ad-4",
      documentId: "doc-ad-4",
      kind: "ad",
      title: "Conference poster",
      artifactType: "a2_conference_poster",
      widthPx: 1191,
      heightPx: 1684,
    }),
  );

  assert.equal(artifact.collateralType, undefined);
});

// ── Thumbnails (2026-08-31 ruling) ─────────────────────────────────────────
// Ruling 2's "real documents have no thumbnails" is superseded: the design API
// renders a lazy, version-cached PNG per document, addressed through the BFF.
// The version in the URL is the cache key, so an edit that bumps
// `currentVersionId` changes the URL and the card picks up the fresh artwork.

test("composes the versioned BFF thumbnail URL for a web document", () => {
  const artifact = toProjectArtifact(
    listItem({ documentId: "doc_w1", currentVersionId: "7" }),
    { now: NOW },
  );

  assert.equal(artifact.imagePath, "/api/clue/design/documents/doc_w1/thumbnail?v=7");
});

test("composes the versioned BFF thumbnail URL for an ad document", () => {
  const artifact = toProjectArtifact(
    listItem({ documentId: "doc_a1", kind: "ad", currentVersionId: "3" }),
    { now: NOW },
  );

  assert.equal(artifact.imagePath, "/api/clue/design/documents/doc_a1/thumbnail?v=3");
});

// ── The account on the feed card (spec §3.8) ───────────────────────────────
// A multi-artifact design leg births one document per target account, so the
// feed row now carries the account it was made for. The mapper writes it onto
// the three fields the designed gallery card already reads, using the
// artifact-library's own favicon rule — no new UI, no new vocabulary.

test("an item's account maps onto the card's account fields", () => {
  const artifact = toProjectArtifact(
    listItem({
      account: { id: "acc_1", name: "Apollo Clinics", domain: "apollo.example" },
    }),
    { now: NOW },
  );

  assert.equal(artifact.accountId, "acc_1");
  assert.equal(artifact.accountName, "Apollo Clinics");
  assert.equal(artifact.accountLogoPath, "/api/source-favicon?domain=apollo.example");
  assert.doesNotThrow(() => ProjectArtifactSchema.parse(artifact));
});

test("a Brandfetch logo on the item wins over the favicon fallback", () => {
  const logoPath =
    "https://cdn.brandfetch.io/domain/apollo.example/w/128/h/128/fallback/lettermark/type/icon?c=cid";
  const artifact = toProjectArtifact(
    listItem({
      account: { id: "acc_1", name: "Apollo Clinics", domain: "apollo.example", logoPath },
    }),
    { now: NOW },
  );

  assert.equal(artifact.accountLogoPath, logoPath);
  assert.doesNotThrow(() => ProjectArtifactSchema.parse(artifact));
});

test("an item with no account keeps the account fields absent", () => {
  const artifact = toProjectArtifact(listItem(), { now: NOW });

  assert.equal("accountId" in artifact, false);
  assert.equal("accountName" in artifact, false);
  assert.equal("accountLogoPath" in artifact, false);
});

test("an account with no domain names itself but claims no logo", () => {
  // The favicon is addressed BY domain; an account the backend knows without
  // one gets no logo path rather than a broken URL.
  const artifact = toProjectArtifact(
    listItem({ account: { id: "acc_2", name: "Northwind Health" } }),
    { now: NOW },
  );

  assert.equal(artifact.accountId, "acc_2");
  assert.equal(artifact.accountName, "Northwind Health");
  assert.equal("accountLogoPath" in artifact, false);
});

test("the wire's nulls and snake_case account survive the seam", () => {
  const [item] = DesignArtifactListWireSchema.parse({
    data: [
      {
        id: "doc-web-1",
        project_id: "prj-1",
        document_id: "doc-web-1",
        kind: "web",
        title: "Launch landing page",
        status: "draft",
        current_version_id: "4",
        created_at: "2026-08-14T09:15:00+00:00",
        updated_at: "2026-08-18T09:15:00+00:00",
        origin_thread_id: "thread-9",
        account: {
          id: "acc_3",
          name: "Apollo Clinics",
          domain: "apollo.example",
          account_entity_id: "ent_7",
        },
      },
    ],
  });

  assert.deepEqual(item.account, {
    id: "acc_3",
    name: "Apollo Clinics",
    domain: "apollo.example",
    accountEntityId: "ent_7",
  });
  // A domain the backend cannot answer is a null on the wire, and the item
  // then simply has no domain — never the string "null".
  const [withoutDomain] = DesignArtifactListWireSchema.parse({
    data: [
      {
        id: "doc-web-2",
        project_id: "prj-1",
        document_id: "doc-web-2",
        kind: "web",
        title: "Launch landing page",
        status: "draft",
        current_version_id: "4",
        created_at: "2026-08-14T09:15:00+00:00",
        updated_at: "2026-08-18T09:15:00+00:00",
        origin_thread_id: "thread-9",
        account: { id: "acc_4", name: "Northwind Health", domain: null, account_entity_id: null },
      },
    ],
  });
  assert.deepEqual(withoutDomain.account, { id: "acc_4", name: "Northwind Health" });
  // A feed row with no account at all stays without the key.
  const [none] = DesignArtifactListWireSchema.parse({
    data: [
      {
        id: "doc-web-3",
        project_id: "prj-1",
        document_id: "doc-web-3",
        kind: "web",
        title: "Launch landing page",
        status: "draft",
        current_version_id: "4",
        created_at: "2026-08-14T09:15:00+00:00",
        updated_at: "2026-08-18T09:15:00+00:00",
        origin_thread_id: "thread-9",
        account: null,
      },
    ],
  });
  assert.equal("account" in none, false);
});

test("an encodeable domain is escaped in the favicon URL", () => {
  const artifact = toProjectArtifact(
    listItem({ account: { id: "acc_5", name: "Acme", domain: "a b&c.example" } }),
    { now: NOW },
  );

  assert.equal(artifact.accountLogoPath, "/api/source-favicon?domain=a%20b%26c.example");
});

test("the mapped account reaches the gallery card's own account slot", () => {
  // `normalizeGalleryArtifact` is what the designed card reads; it composes its
  // `account` from exactly these three fields, and the gallery's account filter
  // matches on it. No new UI: the slot was already there.
  const normalized = normalizeGalleryArtifact(
    toProjectArtifact(
      listItem({ account: { id: "acc_1", name: "Apollo Clinics", domain: "apollo.example" } }),
      { now: NOW },
    ),
  );

  assert.deepEqual(normalized.account, {
    id: "acc_1",
    logoPath: "/api/source-favicon?domain=apollo.example",
    name: "Apollo Clinics",
  });
  assert.equal(
    normalizeGalleryArtifact(toProjectArtifact(listItem(), { now: NOW })).account,
    undefined,
  );
});
