import assert from "node:assert/strict";
import test from "node:test";
import { researchProgressHeadline, researchProgressLine } from "./research-progress-line";
import { ResearchProgressSchema, type ResearchProgress } from "./research-progress";

const base: ResearchProgress = {
  requested_accounts: 10, queued: 3, running: 7, finished: 0, progress_pct: 40, pill: "running",
  last_finished_at: null, attention: [], incident: null,
  agents: [
    { account_name: "OpenAI", stage: "deep_research", subject: "account" },
    { account_name: "Anthropic", stage: "committee", subject: "account" },
    { account_name: "Anthropic", stage: "deep_research", subject: "person" },
    { account_name: "OpenAI", stage: "synthesis", subject: "account" },
  ],
};

test("the headline counts agents and queued accounts", () => {
  assert.equal(researchProgressHeadline(base), "7 research agents running, 3 accounts queued");
  assert.equal(researchProgressHeadline({ ...base, running: 1, queued: 1 }), "1 research agent running, 1 account queued");
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

test("an attention reason is shown as the server's sentence, verbatim", () => {
  const card = ResearchProgressSchema.parse({
    requested_accounts: 10, queued: 0, running: 0, finished: 10, progress_pct: 100,
    pill: "needs_attention", last_finished_at: null, agents: [],
    attention: [{ account_name: "Borland Groover", reason: "Model provider refused: key limit exceeded. Since 16:01. Clue has been notified." }],
    incident: { provider_label: "Model provider", reason_label: "key limit exceeded", since: "2026-09-16T10:31:23Z", affected: 45, notified: true },
  });
  assert.equal(card.incident?.affected, 45);
  assert.equal(
    researchProgressLine(card, 0),
    "Borland Groover: Model provider refused: key limit exceeded. Since 16:01. Clue has been notified.",
  );
});

test("a card from a backend that does not send an incident still parses", () => {
  const card = ResearchProgressSchema.parse({
    requested_accounts: 1, queued: 0, running: 1, finished: 0, progress_pct: 0,
    pill: "running", last_finished_at: null, agents: [], attention: [],
  });
  assert.equal(card.incident, null);
});


test("researcher milestones name the person and survive schema parsing", () => {
  const labels = {
    researching: "researching and reviewing evidence",
    compiling_findings: "compiling research findings",
    storing_claims: "storing claims",
    writing_narrative: "writing the research narrative",
  };
  for (const [stage, label] of Object.entries(labels)) {
    const card = ResearchProgressSchema.parse({ ...base, agents: [{
      account_name: "Acme", subject: "person", subject_name: "Jane Doe", stage,
    }] });
    assert.equal(researchProgressLine(card, 0), `Jane Doe at Acme: ${label}`);
  }
});


test("queued work does not claim research is complete", () => {
  assert.equal(researchProgressLine({ ...base, running: 0, queued: 1, agents: [] }, 0),
    "Research queued for an available agent");
});
