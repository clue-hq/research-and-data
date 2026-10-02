import type { AccountWorkspace } from "../../model/account-workspace";
import { workspaceProfileFixture } from "../workspace-profile.fixture";
import { zafranAccountDetailFixture, zafranContactReferences } from "./account";
import { zafranResearchEvidence } from "./evidence";
import { buildZafranSpecContent } from "./spec-content";

const zafranSpecContent = buildZafranSpecContent({
  contacts: zafranContactReferences,
  evidence: zafranResearchEvidence,
});

export const zafranWorkspaceFixture: AccountWorkspace = {
  accountId: "zafran-security",
  insightSummary: zafranSpecContent.insightSummary,
  researchEvidence: zafranSpecContent.evidence,
  insights: [
    {
      id: "abm-seat",
      source: "link",
      title: "They have been trying to hire an ABM owner for 77 days and have not.",
      sourceLabel: "jobs.ashbyhq.com",
      url: "https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf",
      summary:
        "What it means for us: the work this seat was created for is the work we do, and nobody is doing it.",
    },
  ],
  insightsDisplay: zafranSpecContent.insightsDisplay,
  artifacts: [],
  activity: [
    // Requested visual example only; never a receipt of an executed user action.
    {
      id: "sample-owner-update",
      kind: "updated",
      actor: { type: "person", id: "aakash-shrivastava", name: workspaceProfileFixture.fullName },
      text: "Updated the account",
      action: "updated the account",
      timeLabel: "Sample",
      isSample: true,
    },
    ...zafranAccountDetailFixture.activity,
  ],
};
