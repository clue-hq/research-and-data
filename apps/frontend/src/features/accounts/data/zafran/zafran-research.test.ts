import assert from "node:assert/strict";
import test from "node:test";
import { AccountContactDetailSchema } from "../../model/account-contact";
import { AccountDetailSchema } from "../../model/account-detail";
import { AccountWorkspaceSchema } from "../../model/account-workspace";
import {
  HttpUrlSchema,
  type ResearchDisplayBlock,
} from "../../model/research-display";
import { zafranAccountDetailFixture } from "./account";
import { openAiContactsFixture } from "../account-contacts.fixture";
import { zafranContactDetails, zafranContactsFixture } from "./contacts";
import { zafranResearchEvidence } from "./evidence";
import { zafranWorkspaceFixture } from "./insights";

function assertDisplayBlockReferencesResolve(block: ResearchDisplayBlock) {
  const evidenceIds = new Set(
    zafranWorkspaceFixture.researchEvidence.map((evidence) => evidence.claimId),
  );

  for (const section of block.sections) {
    for (const item of section.items) {
      const claimIds = item.body.flatMap((sentence) => sentence.claimIds);
      claimIds.push(...(item.sendLine?.claimIds ?? []));
      for (const claimId of claimIds) {
        assert.ok(evidenceIds.has(claimId), `Missing evidence ${claimId}`);
      }
      for (const contact of item.contactRefs) {
        assert.ok(
          zafranContactDetails[contact.contactId],
          `Missing contact detail ${contact.contactId}`,
        );
      }
    }
  }
}

test("Zafran account research satisfies the frontend contracts", () => {
  const account = AccountDetailSchema.parse(zafranAccountDetailFixture);
  const workspace = AccountWorkspaceSchema.parse(zafranWorkspaceFixture);

  assert.equal(account.id, "zafran-security");
  assert.equal(account.fitCriteria.length, 0);
  assert.equal(account.buyingCommittee.length, 5);
  // Six researched sections plus the empty Miscellaneous section (2026-09-27, 296922df1).
  assert.equal(workspace.insightsDisplay?.sections.length, 7);
  assert.equal(
    workspace.insightsDisplay?.sections
      .flatMap((section) => section.items)
      .filter((item) => item.newSinceLastVisit).length,
    0,
  );

  assertDisplayBlockReferencesResolve(account.overviewDisplay!);
  assertDisplayBlockReferencesResolve(workspace.insightsDisplay!);
});

test("Zafran source records expose link favicons and linked contacts resolve", () => {
  for (const evidence of zafranResearchEvidence) {
    if (evidence.sourceUrl) {
      assert.ok(evidence.sourceDomain);
      assert.match(evidence.faviconUrl ?? "", /favicons\?domain=/);
    }
  }

  for (const contact of Object.values(zafranContactDetails)) {
    const parsed = AccountContactDetailSchema.parse(contact);
    assert.equal(parsed.accountId, "zafran-security");
    if (parsed.contactDisplay) {
      assertDisplayBlockReferencesResolve(parsed.contactDisplay);
    }
  }
});

test("research links only accept browser-safe HTTP protocols", () => {
  assert.equal(HttpUrlSchema.safeParse("https://zafran.io").success, true);
  assert.equal(HttpUrlSchema.safeParse("http://localhost:5000").success, true);
  assert.equal(HttpUrlSchema.safeParse("javascript:alert(1)").success, false);
  assert.equal(HttpUrlSchema.safeParse("data:text/html,test").success, false);
});

test("contact rows only expose navigation when a valid destination exists", () => {
  assert.ok(
    zafranContactsFixture.every(
      (contact) =>
        contact.profileAction === "page" &&
        Boolean(zafranContactDetails[contact.id]),
    ),
  );
  assert.equal(
    openAiContactsFixture.find((contact) => contact.id === "denise-dresser")
      ?.profileAction,
    "preview",
  );
  assert.equal(
    openAiContactsFixture.find((contact) => contact.id === "brad-lightcap")
      ?.profileAction,
    "none",
  );
  assert.ok(
    zafranContactsFixture.every((contact) =>
      contact.emailStatus === "available"
        ? Boolean(contact.emailLabel)
        : !contact.emailLabel,
    ),
  );
});
