import assert from "node:assert/strict";
import test from "node:test";
import { WorkspaceInsightSchema } from "./account-workspace";
import {
  EvidenceReferenceSchema,
  accountEvidenceArtifactHref,
  contactEvidenceArtifactHref,
  exactEvidenceSourceLabel,
} from "./evidence";

test("public evidence labels are the exact safe target", () => {
  const exact = "https://evidence.example/reports/committee?version=2#finding";
  const evidence = EvidenceReferenceSchema.parse({
    claimId: "claim-1",
    fieldKey: "contact.current_title",
    sourceTitle: "official_site",
    sourceUrl: exact,
    evidenceSpan: "Dana Buyer is the current VP of Finance.",
    confidence: 0.94,
    freshness: "fresh",
    observedAt: "2026-08-01T00:00:00Z",
    protectedArtifactAvailable: true,
  });

  assert.equal(evidence.sourceUrl, exact);
  assert.equal(exactEvidenceSourceLabel(evidence.sourceUrl), exact);
  assert.throws(
    () => EvidenceReferenceSchema.parse({ ...evidence, sourceUrl: "javascript:alert(1)" }),
    /public evidence URLs must use http or https/,
  );
  assert.throws(
    () =>
      EvidenceReferenceSchema.parse({
        ...evidence,
        sourceUrl: "https://user:secret@evidence.example/reports/committee",
      }),
    /without embedded credentials/,
  );
});

test("legacy workspace insights reject a label that overstates URL precision", () => {
  assert.throws(
    () =>
      WorkspaceInsightSchema.parse({
        id: "insight-1",
        source: "link",
        title: "Enterprise AI",
        sourceLabel: "https://example.test/reports/enterprise-ai",
        url: "https://example.test/",
        summary: "An evidence-backed finding.",
      }),
    /sourceLabel must exactly equal url/,
  );
});

test("retained evidence actions stay same-origin and contain no storage locator", () => {
  assert.equal(
    accountEvidenceArtifactHref("account/1", "claim/1"),
    "/api/clue/frontend/v1/accounts/account%2F1/evidence/claim%2F1",
  );
  assert.equal(
    contactEvidenceArtifactHref("account/1", "contact/1", "claim/1"),
    "/api/clue/frontend/v1/accounts/account%2F1/contacts/contact%2F1/evidence/claim%2F1",
  );
});
