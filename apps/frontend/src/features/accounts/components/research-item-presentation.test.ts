import assert from "node:assert/strict";
import test from "node:test";
import { nickFisherFixture } from "../data/zafran/contacts";
import { presentResearchItem } from "./research-item-presentation";

test("a standalone heading reference does not create an orphan punctuation line", () => {
  const item = nickFisherFixture.contactDisplay!.sections
    .find((section) => section.key === "problem-right-now")!.items[1]!;
  const original = JSON.stringify(item);
  const presented = presentResearchItem(item);

  assert.equal(nickFisherFixture.researchEvidence.find((record) => record.claimId === presented.headingClaimIds[0])?.sourceUrl, "https://jobs.ashbyhq.com/zafran-security");
  assert.equal(presented.body[0]!.text.trim(), 'Zafran\'s CEO told the press "we need more people".');
  assert.equal(nickFisherFixture.researchEvidence.find((record) => record.claimId === presented.body[0]!.claimIds[0])?.sourceDomain, "calcalistech.com");
  assert.equal(JSON.stringify(item), original, "The supplied research must not be modified");
});

test("ordinary research paragraphs retain their text and evidence placement", () => {
  const item = nickFisherFixture.contactDisplay!.sections[0]!.items[0]!;
  assert.deepEqual(presentResearchItem(item), { headingClaimIds: [], body: item.body });
});
