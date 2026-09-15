import assert from "node:assert/strict";
import test from "node:test";
import {
  ProjectDocumentsResponseSchema,
  ProjectDocumentSaveSchema,
  documentEditedLabel,
  documentKindLabel,
  planDocumentOf,
  toProjectDocument,
} from "./project-documents";

const summary = {
  id: "doc-1", path: "project/plan.md", kind: "project-plan", title: "Plan",
  version: 2, status: "ready", updated_at: "2026-09-13T08:00:00Z", icp_key: null,
};

test("document lists map backend fields without inventing content or an ICP key", () => {
  const wire = ProjectDocumentsResponseSchema.parse({ data: { documents: [summary] } });
  assert.deepEqual(toProjectDocument(wire.data.documents[0]), {
    id: "doc-1", path: "project/plan.md", kind: "project-plan", title: "Plan",
    version: 2, status: "ready", updatedAt: summary.updated_at, icpKey: null,
  });
  assert.deepEqual(ProjectDocumentsResponseSchema.parse({ data: { documents: [] } }).data.documents, []);
  for (const invalid of [{ version: 0 }, { kind: "" }, { updated_at: "yesterday" }]) {
    assert.equal(ProjectDocumentsResponseSchema.safeParse({ data: { documents: [{ ...summary, ...invalid }] } }).success, false);
  }
});

test("a document's kind is the word its own front matter says, never a closed list", () => {
  // Founder ruling 2026-09-14: the agent writes any document under project/ and names its kind
  // itself; the backend serves that word as is. A kind the frontend has never seen must not
  // fail the whole list — that hid every document in the Gallery on 2026-09-15.
  for (const kind of ["campaign-plan", "competitive-brief", "meeting-notes"]) {
    const parsed = ProjectDocumentsResponseSchema.safeParse({ data: { documents: [{ ...summary, kind }] } });
    assert.equal(parsed.success, true);
    assert.equal(parsed.success && toProjectDocument(parsed.data.data.documents[0]).kind, kind);
  }
});

test("known kinds keep their labels and an unknown kind is read as its own words", () => {
  assert.equal(documentKindLabel("project-plan"), "Plan");
  assert.equal(documentKindLabel("icp-definition"), "Ideal customer profile");
  assert.equal(documentKindLabel("audience-persona"), "Personas");
  assert.equal(documentKindLabel("campaign-plan"), "Campaign plan");
  assert.equal(documentKindLabel("competitive-brief"), "Competitive brief");
  assert.equal(documentKindLabel("notes"), "Notes");
});

test("the plan is selected by its canonical path, not a title or another project's filename", () => {
  const plan = toProjectDocument(ProjectDocumentsResponseSchema.parse({ data: { documents: [summary] } }).data.documents[0]);
  const other = { ...plan, id: "doc-2", path: "audience/plan.md" };
  assert.equal(planDocumentOf([other, plan]), plan);
  assert.equal(planDocumentOf([other]), null);
  assert.equal(planDocumentOf([]), null);
});

test("edited labels cover just now, minutes, earlier today and older dates", () => {
  const now = new Date(2026, 8, 13, 15, 0);
  const label = (date: Date) => documentEditedLabel(date.toISOString(), now);
  assert.equal(label(new Date(2026, 8, 13, 14, 59, 45)), "Edited just now");
  assert.equal(label(new Date(2026, 8, 13, 14, 55)), "Edited 5 min ago");
  assert.equal(label(new Date(2026, 8, 13, 14, 0)), "Edited today at 14:00");
  assert.equal(label(new Date(2026, 8, 12, 14, 0)), "Edited 12 Sep");
  assert.equal(label(new Date(2026, 8, 13, 15, 0, 30)), "Edited just now");
});

test("save accepts raw Markdown only with a positive base revision", () => {
  const body = "  # Plan\n\nKeep my spacing.\n";
  assert.deepEqual(ProjectDocumentSaveSchema.parse({ body, expectedRevision: 2 }), { body, expectedRevision: 2 });
  for (const payload of [
    { body: " \n", expectedRevision: 2 },
    { body, expectedRevision: "2" },
    { body, expectedRevision: 0 },
    { body, expectedRevision: 2, front_matter: { status: "confirmed" } },
  ]) assert.equal(ProjectDocumentSaveSchema.safeParse(payload).success, false);
});
