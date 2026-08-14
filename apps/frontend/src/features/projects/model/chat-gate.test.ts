import assert from "node:assert/strict";
import test from "node:test";
import { ChatGateListResponseSchema, gateCardModel } from "./chat-gate";
import { ChatPartSnapshotSchema, type ChatGatePart } from "./chat-parts";
import { fixtureGates } from "../data/chat.fixture";

/** The gate-card state machine: requested → responded / denied, plus unavailable. */

function part(overrides: Record<string, unknown> = {}): ChatGatePart {
  const parsed = ChatPartSnapshotSchema.parse({
    part_id: "gate:agent_gate:g1",
    kind: "gate",
    revision: 1,
    gate_ref: { object_type: "agent_gate", object_id: "g1" },
    // What the backend actually sends today: the ref's object type as the kind,
    // and nothing else. The card must survive it.
    gate_kind: "agent_gate",
    state: "requested",
    ...overrides,
  });
  assert.equal(parsed.kind, "gate");
  return parsed as ChatGatePart;
}

const [openGate] = ChatGateListResponseSchema.parse({ data: fixtureGates });

test("a durable gate makes the card answerable", () => {
  const card = gateCardModel({ gate: openGate, part: part() });
  assert.ok(card);
  assert.equal(card.state, "requested");
  assert.equal(card.kind, "directive_confirmation");
  assert.equal(card.amountCents, 24000);
  assert.equal(card.expectedSubjectSha256, openGate.expectedSubjectSha256);
  assert.deepEqual(card.permittedDecisions, ["approved", "rejected", "revised"]);
});

test("a durable gate with a withheld amount is still answerable, with no cost", () => {
  // The pilot posture (`CLUE_BUDGET_CONTROLS_ENABLED` off): the amount stays on
  // the immutable row and never crosses. The digest does, so the card works.
  const card = gateCardModel({
    gate: { ...openGate, maxSpendCents: null },
    part: part(),
  });
  assert.ok(card);
  assert.equal(card.state, "requested");
  assert.equal(card.amountCents, null);
  assert.equal(card.unavailableReason, null);
});

test("a part with no durable payload is unavailable, not answerable", () => {
  const card = gateCardModel({ gate: null, part: part() });
  assert.ok(card);
  assert.equal(card.state, "unavailable");
  assert.ok(card.unavailableReason);
  assert.equal(card.expectedSubjectSha256, null);
  assert.equal(card.amountCents, null);
});

test("a gate part that carries the full snapshot is answerable without the read", () => {
  const card = gateCardModel({
    gate: null,
    part: part({
      gate_kind: "directive_confirmation",
      expected_subject_sha256: "b".repeat(64),
      amount_cents: 500,
      currency: "USD",
      title: "Confirm the launch",
    }),
  });
  assert.ok(card);
  assert.equal(card.state, "requested");
  assert.equal(card.title, "Confirm the launch");
  assert.equal(card.amountCents, 500);
});

test("an approved gate stays in history as responded, with its decision", () => {
  const answered = {
    ...openGate,
    answer: {
      turnId: "t2",
      actionRef: "turn-action:t2",
      decision: "approved",
      selectedOptionRef: null,
      answeredByUserId: "usr_demo",
      answeredAt: "2026-08-09T11:10:00Z",
    },
    launches: [
      {
        researchRunId: "r1",
        runKind: "account_research",
        runState: "running",
        sourceActionRef: "turn-action:t2",
        approvalRefs: ["turn-action:t2"],
      },
    ],
  };
  const card = gateCardModel({ gate: answered, part: part() });
  assert.ok(card);
  assert.equal(card.state, "responded");
  assert.equal(card.decision, "approved");
  assert.equal(card.answeredByUserId, "usr_demo");
  assert.equal(card.launches.length, 1);
});

test("a rejected or revised gate is denied — closed, recorded, never re-answerable", () => {
  for (const decision of ["rejected", "revised"] as const) {
    const card = gateCardModel({
      gate: {
        ...openGate,
        answer: {
          turnId: "t3",
          actionRef: "turn-action:t3",
          decision,
          selectedOptionRef: null,
          answeredByUserId: "usr_demo",
          answeredAt: "2026-08-09T11:12:00Z",
        },
      },
      part: part(),
    });
    assert.ok(card);
    assert.equal(card.state, "denied");
    assert.equal(card.decision, decision);
  }
});

test("no gate and no part is no card at all", () => {
  assert.equal(gateCardModel({ gate: null, part: null }), null);
});

test("permitted decisions narrow to the ones the backend allowed", () => {
  const card = gateCardModel({
    gate: openGate,
    part: part({ permitted_decisions: ["approved", "rejected", "nonsense"] }),
  });
  assert.ok(card);
  assert.deepEqual(card.permittedDecisions, ["approved", "rejected"]);
});

test("a product-selection gate exposes only its durable catalog choices", () => {
  const [gate] = ChatGateListResponseSchema.parse({
    data: [
      {
        ...fixtureGates[0],
        kind: "product_selection",
        max_spend_cents: "0",
        subject_snapshot: {
          products: [
            {
              product_id: "prd_phone",
              name: "AI Phone Agents",
              short_description: "Healthcare call and scheduling automation",
              aliases: ["Insight Voice"],
              status: "active",
            },
            {
              product_id: "prd_intake",
              name: "Patient Intake",
              short_description: "Digital patient intake workflows",
              aliases: [],
              status: "active",
            },
            { product_id: "invalid-without-description", name: "Invalid" },
          ],
        },
      },
    ],
  });
  const card = gateCardModel({ gate, part: part() });
  assert.ok(card);
  assert.equal(card.kind, "product_selection");
  assert.deepEqual(
    card.productOptions.map((item) => item.productId),
    ["prd_phone", "prd_intake"],
  );
  assert.equal(card.productOptions[0]?.aliases[0], "Insight Voice");
});

test("an answered product gate retains the exact selected option", () => {
  const [gate] = ChatGateListResponseSchema.parse({
    data: [
      {
        ...fixtureGates[0],
        kind: "product_selection",
        subject_snapshot: {
          products: [
            {
              product_id: "prd_phone",
              name: "AI Phone Agents",
              short_description: "Healthcare call automation",
              aliases: [],
              status: "active",
            },
          ],
        },
        answer: {
          turn_id: "turn-selection",
          action_ref: "turn-action:turn-selection",
          decision: "approved",
          selected_option_ref: "prd_phone",
          answered_by_user_id: "usr_demo",
          answered_at: "2026-08-15T12:00:00Z",
        },
      },
    ],
  });
  const card = gateCardModel({ gate, part: part() });
  assert.ok(card);
  assert.equal(card.state, "responded");
  assert.equal(card.selectedProductId, "prd_phone");
});
