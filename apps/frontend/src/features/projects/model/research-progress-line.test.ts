import assert from "node:assert/strict";
import test from "node:test";
import { researchProgressHeadline, researchProgressLine } from "./research-progress-line";
import type { ResearchProgress } from "./research-progress";

const base: ResearchProgress = {
  requested_accounts: 10, queued: 3, running: 7, finished: 0, progress_pct: 40, pill: "running",
  last_finished_at: null, attention: [],
  agents: [
    { account_name: "OpenAI", stage: "deep_research", subject: "account" },
    { account_name: "Anthropic", stage: "committee", subject: "account" },
    { account_name: "Anthropic", stage: "deep_research", subject: "person" },
    { account_name: "OpenAI", stage: "synthesis", subject: "account" },
  ],
};

test("the headline counts agents and queued accounts", () => {
  assert.equal(researchProgressHeadline(base), "7 account research agents running, 3 accounts queued");
  assert.equal(researchProgressHeadline({ ...base, running: 1, queued: 1 }), "1 account research agent running, 1 account queued");
});

test("the line rotates round-robin over the running agents, worded by stage", () => {
  assert.equal(researchProgressLine(base, 0), "OpenAI agent doing deep research");
  assert.equal(researchProgressLine(base, 1), "Finding the buying committee for Anthropic");
  assert.equal(researchProgressLine(base, 2), "Diving deeper into each committee member of Anthropic");
  assert.equal(researchProgressLine(base, 3), "Synthesising our findings for OpenAI");
  assert.equal(researchProgressLine(base, 4), "OpenAI agent doing deep research");
});

test("completed and needs-attention have their own lines", () => {
  assert.equal(researchProgressLine({ ...base, pill: "completed", agents: [], finished: 10 }, 5), "Research complete for 10 accounts");
  assert.equal(
    researchProgressLine({ ...base, pill: "needs_attention", attention: [{ account_name: "Cove", reason: "the model errored" }] }, 0),
    "Cove: the model errored",
  );
});
