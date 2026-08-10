import assert from "node:assert/strict";
import test from "node:test";
import {
  ChatInspectorCapabilitySchema,
  ChatInspectorContextResponseSchema,
  ChatInspectorPlanResponseSchema,
  ChatInspectorRoundsResponseSchema,
  ChatInspectorToolsResponseSchema,
  bodyPlaceholder,
  budgetRatio,
  layerLabel,
} from "./chat-inspector";
import {
  fixtureInspectorContext,
  fixtureInspectorPlan,
  fixtureInspectorRounds,
  fixtureInspectorTools,
} from "../data/chat.fixture";

/**
 * The dev-lens inspector's wire contract, at the repository boundary.
 *
 * The properties worth testing are the honest-gap ones: an absent context
 * bundle stays `null` rather than becoming an empty seven-layer skeleton, an
 * over-budget body stays absent rather than becoming shortened text, and an
 * admitted-but-never-completed operation keeps its row rather than vanishing.
 * Those are the cases a developer opens the drawer to see.
 */

const TURN = "8c4a0b1e-0000-4000-8000-000000000001";

test("a turn that assembled no context parses as null, not as an empty bundle", () => {
  assert.equal(ChatInspectorContextResponseSchema.parse({ data: null }), null);
});

test("the context tab carries budgets, included bytes, and dropped pointers", () => {
  const view = ChatInspectorContextResponseSchema.parse(fixtureInspectorContext(TURN));
  assert.ok(view);
  assert.equal(view.turnId, TURN);
  assert.equal(view.policyVersion, "conversation-v3");

  const identity = view.layers.find((layer) => layer.layer === "l1_identity");
  assert.ok(identity);
  assert.equal(identity.tokenCount, 384);
  assert.equal(identity.tokenBudget, 2000);
  // The exact bytes that were put in front of the model.
  assert.match(identity.refs[0].body?.text ?? "", /Head of ABM/);
  assert.equal(identity.refs[0].body?.omittedReason, null);

  // Over budget: withheld whole, with its address kept so it can still be
  // fetched deliberately. Never a shortened string.
  const memory = view.layers.find((layer) => layer.layer === "l4_memory");
  assert.ok(memory);
  assert.equal(memory.refs[0].body?.text, null);
  assert.equal(memory.refs[0].body?.omittedReason, "budget");
  assert.ok(memory.refs[0].body?.artifactKey);
  assert.equal(view.truncated, true);

  // A dropped pointer keeps its reason and carries no body: it was never shown
  // to the model, so there is nothing about its bytes to report.
  const conversation = view.layers.find((layer) => layer.layer === "l6_conversation");
  assert.ok(conversation);
  assert.equal(conversation.refs[0].disposition, "excluded");
  assert.equal(conversation.refs[0].exclusionReasonCode, "layer_budget_exhausted");
  assert.equal(conversation.refs[0].body, null);
});

test("the rounds tab keeps the requested and the answering model apart", () => {
  const rounds = ChatInspectorRoundsResponseSchema.parse(fixtureInspectorRounds());
  assert.equal(rounds.length, 2);
  assert.equal(rounds[0].requestedModel, rounds[0].answeringModel);
  // A gateway fallback fired: showing one id only would turn "we asked for X"
  // into "we called X".
  assert.notEqual(rounds[1].requestedModel, rounds[1].answeringModel);
  assert.equal(rounds[1].answeringModel, "anthropic/claude-sonnet-4");
  assert.equal(rounds[0].costMillicredits, 143);
});

test("the plan tab serves both documents and the turn ledger a refusal lives in", () => {
  const view = ChatInspectorPlanResponseSchema.parse(fixtureInspectorPlan(TURN));
  const plan = view.plans[0];
  const authored = JSON.parse(plan.proposal.text ?? "{}");
  const admitted = JSON.parse(plan.validated.text ?? "{}");
  // Both, so "which step did validation drop?" is answered from receipts rather
  // than from a re-derivation on either side of the wire.
  assert.deepEqual(
    authored.steps.map((step: { node_key: string }) => step.node_key),
    ["agent_draft_directive_01", "agent_fetch_page_02"],
  );
  assert.deepEqual(
    admitted.steps.map((step: { node_key: string }) => step.node_key),
    ["agent_draft_directive_01"],
  );
  assert.equal(plan.operations.length, 1);
  assert.equal(plan.operations[0].validation, "admitted");

  // A plan the validator rejects is never journaled, so it has no per-operation
  // verdict; its refusal is in the turn's own ledger and nowhere else.
  assert.ok(
    view.turnEvents.some(
      (event) => event.status === "failed" && event.reasonCode === "plan_rejected",
    ),
  );
});

test("the tools tab keeps an admitted operation that never completed", () => {
  const view = ChatInspectorToolsResponseSchema.parse(fixtureInspectorTools(TURN));
  assert.equal(view.calls.length, 2);
  const completed = view.calls[0];
  assert.deepEqual(JSON.parse(completed.arguments.text ?? "{}").account_count, 2);
  assert.equal(completed.replayed, false);
  assert.equal(completed.referenceCount, 1);

  // Dropping this row would hide precisely the call a developer opened the tab
  // to find.
  const failed = view.calls[1];
  assert.equal(failed.result, null);
  assert.equal(failed.completedAt, null);
});

test("capability is a payload, not an environment variable", () => {
  const capability = ChatInspectorCapabilitySchema.parse({
    data: {
      enabled: true,
      tabs: ["context", "rounds", "plan", "tools"],
      budget_bytes: 512_000,
      bodies_available: false,
    },
  });
  assert.equal(capability.enabled, true);
  assert.equal(capability.bodiesAvailable, false);
  assert.deepEqual(capability.tabs, ["context", "rounds", "plan", "tools"]);
});

test("a budget meter never reads full for a layer that was allotted nothing", () => {
  assert.equal(budgetRatio(0, 0), 0);
  assert.equal(budgetRatio(50, 0), 0);
  assert.equal(budgetRatio(500, 1000), 0.5);
  // Clamped: a receipt that somehow overspends its budget still renders a meter.
  assert.equal(budgetRatio(2000, 1000), 1);
});

test("an absent body always says which of the four reasons applies", () => {
  const address = { artifactKey: "ws/abc", sha256: "abc" };
  assert.equal(bodyPlaceholder({ ...address, text: "hello", omittedReason: null }), null);
  assert.match(
    bodyPlaceholder({ ...address, text: null, omittedReason: "budget" }) ?? "",
    /withheld/,
  );
  assert.match(
    bodyPlaceholder({ ...address, text: null, omittedReason: "digest_mismatch" }) ?? "",
    /no longer match/,
  );
  assert.match(
    bodyPlaceholder({ ...address, text: null, omittedReason: "not_text" }) ?? "",
    /Not a text artifact/,
  );
  // An unknown reason code is still reported as absent, never as empty text.
  assert.equal(
    bodyPlaceholder({ ...address, text: null, omittedReason: "who_knows" }),
    "Unavailable.",
  );
});

test("layer labels fall back to the wire name rather than inventing one", () => {
  assert.equal(layerLabel("l1_identity"), "L1 · Identity");
  assert.equal(layerLabel("l8_future"), "l8_future");
});
