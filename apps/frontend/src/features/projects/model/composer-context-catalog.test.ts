import assert from "node:assert/strict";
import test from "node:test";
import {
  accountTreeRows,
  buildComposerCatalog,
  composerCategoryCounts,
  contactCountsByAccount,
  detectMentionQuery,
  entityCategory,
  searchComposerCatalog,
  shouldAutoCloseMention,
} from "./composer-context-catalog";
import type { ProjectDocument } from "./project-documents";
import type { ProjectArtifact, ProjectEntity } from "./project-workspace";

const plan: ProjectDocument = {
  id: "doc-plan",
  path: "project/plan.md",
  kind: "project-plan",
  title: "Q4 expansion plan",
  version: 3,
  status: "ready",
  updatedAt: "2026-09-17T10:00:00+00:00",
  icpKey: null,
};
const site: ProjectArtifact = {
  documentId: "design-site",
  editedLabel: "Edited today",
  id: "design-site",
  originThreadId: "thr_1",
  title: "Spring launch page",
  type: "website",
  version: 4,
};
const ad: ProjectArtifact = {
  collateralType: "linkedin-ad",
  documentId: "design-ad",
  editedLabel: "Edited today",
  id: "design-ad",
  originThreadId: "thr_1",
  title: "GI North ad",
  type: "canvas",
  version: 2,
};
const table: ProjectArtifact = {
  editedLabel: "Edited today",
  id: "table-1",
  originThreadId: "thr_1",
  title: "Target accounts",
  type: "table",
};
const account: ProjectEntity = {
  id: "acct-1",
  imagePath: "/logos/clue.svg",
  label: "Lane Regional Medical Center",
  secondaryLabel: "lanermc.org",
  type: "account",
  version: 5,
};
const contact: ProjectEntity = {
  accountId: "acct-1",
  accountName: "Lane Regional Medical Center",
  id: "ctc-1",
  label: "Pat Lee",
  secondaryLabel: "Chief Executive Officer",
  type: "contact",
  version: 2,
};
const otherAccount: ProjectEntity = {
  id: "acct-2",
  label: "Baylor Scott & White Health",
  secondaryLabel: "bswhealth.com",
  type: "account",
  version: 1,
};
const strayContact: ProjectEntity = {
  accountId: "acct-gone",
  id: "ctc-9",
  label: "Sam Roe",
  secondaryLabel: "CFO",
  type: "contact",
  version: 1,
};

test("the catalog puts documents and ads under files, web documents under microsites", () => {
  const catalog = buildComposerCatalog({
    documents: [plan],
    artifacts: [site, ad, table],
    entities: [account],
  });
  assert.deepEqual(
    catalog.map((entity) => [entity.id, entityCategory(entity), entity.type, entity.version]),
    [
      ["doc-plan", "files", "project_document", 3],
      ["design-ad", "files", "design_document", 2],
      ["design-site", "microsites", "design_document", 4],
      ["acct-1", "accounts", "account", 5],
    ],
  );
  const file = catalog[0]!;
  assert.equal(file.label, "Q4 expansion plan");
  assert.equal(file.secondaryLabel, "Plan");
  assert.equal(file.icon, "file-text");
  assert.equal(catalog[1]!.secondaryLabel, "LinkedIn ad");
  assert.equal(catalog[1]!.icon, "image");
  assert.equal(catalog[2]!.secondaryLabel, "Microsite");
  assert.equal(catalog[2]!.icon, "web");
  assert.deepEqual(composerCategoryCounts(catalog), { files: 2, microsites: 1, accounts: 1 });
  for (const entity of catalog) {
    assert.equal(JSON.stringify(entity).includes("project/plan.md"), false);
  }
});

test("an artifact without a design document id or a positive version is not offered", () => {
  const catalog = buildComposerCatalog({
    documents: [],
    artifacts: [{ ...site, documentId: undefined }, { ...ad, version: undefined }],
    entities: [],
  });
  assert.deepEqual(catalog, []);
});

test("search runs across every category and keeps category order", () => {
  const catalog = buildComposerCatalog({
    documents: [plan],
    artifacts: [site, ad],
    entities: [account],
  });
  assert.deepEqual(
    searchComposerCatalog(catalog, "la").map((entity) => entity.id),
    ["doc-plan", "design-site", "acct-1"],
  );
  assert.deepEqual(searchComposerCatalog(catalog, "  "), []);
  assert.deepEqual(searchComposerCatalog(catalog, "north ad").map((e) => e.id), ["design-ad"]);
});

test("the mention query allows spaces, stops at a second @, and is capped", () => {
  assert.equal(detectMentionQuery("hello @Project plan"), "Project plan");
  assert.equal(detectMentionQuery("@"), "");
  assert.equal(detectMentionQuery("email me@example.com"), null);
  assert.equal(detectMentionQuery("@a @b"), "b");
  assert.equal(detectMentionQuery(`@${"x".repeat(61)}`), null);
  assert.equal(shouldAutoCloseMention("meet ", 0), true);
  assert.equal(shouldAutoCloseMention("meet", 0), false);
  assert.equal(shouldAutoCloseMention("meet ", 2), false);
});

test("the accounts count counts accounts, not the contacts beneath them", () => {
  const catalog = buildComposerCatalog({
    documents: [plan],
    artifacts: [],
    entities: [account, contact, otherAccount],
  });
  assert.deepEqual(composerCategoryCounts(catalog), { files: 1, microsites: 0, accounts: 2 });
  assert.deepEqual([...contactCountsByAccount(catalog)], [["acct-1", 1]]);
});

test("the accounts tree unfolds an account's contacts only while it is expanded", () => {
  const catalog = buildComposerCatalog({
    documents: [],
    artifacts: [],
    entities: [account, contact, otherAccount, strayContact],
  });
  assert.deepEqual(
    accountTreeRows(catalog, new Set()).map((entity) => entity.id),
    ["acct-1", "acct-2", "ctc-9"],
  );
  assert.deepEqual(
    accountTreeRows(catalog, new Set(["acct-1"])).map((entity) => entity.id),
    ["acct-1", "ctc-1", "acct-2", "ctc-9"],
  );
  // Search stays flat and still reaches the contact by its account's name.
  assert.deepEqual(
    searchComposerCatalog(catalog, "lane regional").map((entity) => entity.id),
    ["acct-1", "ctc-1"],
  );
});
