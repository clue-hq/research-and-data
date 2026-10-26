import assert from "node:assert/strict";
import test from "node:test";
import {
  ChatGateListResponseSchema,
  agentGateIdFromPart,
  gateAnswerDisplay,
  gateAnswerResponse,
  gateAuthorityFailure,
  gateCardModel,
  gateDecisionCopy,
  type ChatGate,
} from "./chat-gate";
import { ChatPartSnapshotSchema, type ChatGatePart } from "./chat-parts";
import { fixtureGates } from "../data/chat.fixture";

/** Durable authority, not stream richness, drives every interactive state. */

const [openGate] = ChatGateListResponseSchema.parse({ data: fixtureGates });

const SCOPE = {
  currentUserId: "usr_demo",
  currentWorkspaceId: "ws-demo",
  expectedProjectId: openGate.projectId,
  expectedThreadId: openGate.threadId,
  gateReadAvailable: true,
} as const;

function part(overrides: Record<string, unknown> = {}): ChatGatePart {
  const parsed = ChatPartSnapshotSchema.parse({
    part_id: `gate:agent_gate:${openGate.gateId}`,
    kind: "gate",
    revision: 1,
    gate_ref: { object_type: "agent_gate", object_id: openGate.gateId },
    gate_kind: "agent_gate",
    state: "requested",
    ...overrides,
  });
  assert.equal(parsed.kind, "gate");
  return parsed as ChatGatePart;
}

function model({
  gate = openGate,
  gatePart = part(),
  ...scope
}: {
  gate?: ChatGate | null;
  gatePart?: ChatGatePart | null;
  currentUserId?: string | null;
  currentWorkspaceId?: string | null;
  expectedProjectId?: string;
  expectedThreadId?: string;
  gateReadAvailable?: boolean;
  gateReadLoading?: boolean;
  authorityFailure?: ReturnType<typeof gateAuthorityFailure> | null;
} = {}) {
  return gateCardModel({
    gate,
    part: gatePart,
    ...SCOPE,
    ...scope,
  });
}

test("a fetched, supported, exactly scoped and addressed gate is answerable", () => {
  const card = model();
  assert.ok(card);
  assert.equal(card.state, "requested");
  assert.equal(card.kind, "directive_confirmation");
  assert.equal(card.amountCents, 24000);
  assert.equal(card.expectedSubjectSha256, openGate.expectedSubjectSha256);
  assert.deepEqual(card.permittedDecisions, ["approved", "rejected", "revised"]);
  assert.equal(card.recovery, null);
});

test("a durable gate with a withheld amount remains answerable without a cost", () => {
  const card = model({ gate: { ...openGate, maxSpendCents: null } });
  assert.ok(card);
  assert.equal(card.state, "requested");
  assert.equal(card.amountCents, null);
});

test("a scope-only discovery gate renders its account count and typed revision", () => {
  const discovery = model({
    gate: {
      ...openGate,
      maxSpendCents: null,
      currency: null,
      subjectSnapshot: {
        subject_kind: "discovery_configuration",
        approved_icp_ref: "icp-spec:ws-demo:health:v1",
        planning_policy_version: "stage0-discovery-planning-policy@1",
        configuration: {
          schema_version: "stage0-discovery-configuration@1",
          approved_icp_ref: "icp-spec:ws-demo:health:v1",
          entity_type: "company",
          requested_account_count: 10,
          search_intent: "Find specialty healthcare practices.",
          must_have_criteria: ["Specialty healthcare"],
          exclusion_criteria: ["Current customers"],
        },
      },
    },
  });

  assert.ok(discovery);
  assert.equal(discovery.title, "Review account discovery scope");
  assert.equal(discovery.summary, "Discover 10 accounts using the approved ICP criteria");
  assert.equal(discovery.revisionKind, "discovery");
  assert.deepEqual(
    gateAnswerResponse(discovery, {
      kind: "discovery_revision",
      decision: "revised",
      revisionRequest: "  Start with 50 and exclude hospitals.  ",
    }),
    {
      gateId: openGate.gateId,
      decision: "revised",
      expectedSubjectSha256: openGate.expectedSubjectSha256,
      expectedEstimatedCostCents: null,
      revisionRequest: "Start with 50 and exclude hospitals.",
    },
  );
});

test("a rich stream part can never substitute for the durable gate read", () => {
  const card = model({
    gate: null,
    gatePart: part({
      gate_kind: "directive_confirmation",
      expected_subject_sha256: "b".repeat(64),
      amount_cents: 500,
      currency: "USD",
      title: "Pretend authority",
      permitted_decisions: ["approved", "rejected", "revised"],
    }),
  });
  assert.ok(card);
  assert.equal(card.state, "unavailable");
  assert.equal(card.title, "Human action required");
  assert.equal(card.expectedSubjectSha256, null);
  assert.deepEqual(card.permittedDecisions, []);
  assert.equal(card.recovery?.kind, "request_new_gate");
});

test("a privacy-redacted durable gate is unavailable with no choices or actions", () => {
  const card = model({
    gate: {
      ...openGate,
      kind: "product_selection",
      subjectSnapshot: {},
      snapshotErasedAt: "2026-08-15T12:30:00Z",
      snapshotErasureReason: "dsar_subject_erasure",
    },
  });
  assert.ok(card);
  assert.equal(card.state, "unavailable");
  assert.match(card.unavailableReason ?? "", /reviewed subject was erased/);
  assert.deepEqual(card.permittedDecisions, []);
  assert.deepEqual(card.productOptions, []);
});

test("human_only and non-agent refs are model-only notices, never object ids", () => {
  for (const gateRef of [
    { object_type: "icp_confirmation", object_id: "human_only" },
    { object_type: "agent_gate", object_id: "human_only" },
    { object_type: "stage0_readiness_decision", object_id: openGate.gateId },
  ]) {
    const gatePart = part({ gate_ref: gateRef });
    assert.equal(agentGateIdFromPart(gatePart), null);
    const card = model({ gate: null, gatePart });
    assert.ok(card);
    assert.equal(card.state, "unavailable");
    assert.deepEqual(card.permittedDecisions, []);
    assert.match(card.unavailableReason ?? "", /incomplete/);
  }
});

test("a missing row and a failed gate read have distinct recovery actions", () => {
  const missing = model({ gate: null });
  assert.ok(missing);
  assert.equal(missing.recovery?.kind, "request_new_gate");

  const failed = model({
    gate: null,
    gateReadAvailable: false,
  });
  assert.ok(failed);
  assert.equal(failed.recovery?.kind, "retry_gate_read");
  assert.equal(
    failed.unavailableReason,
    "We couldn't load the approval details. Please try again.",
  );
});

test("scope, conversation, addressee and revision are all required", () => {
  const cases = [
    model({ currentWorkspaceId: "ws_other" }),
    model({ expectedProjectId: "prj_other" }),
    model({ expectedThreadId: "thr_other" }),
    model({ currentUserId: "usr_other" }),
    model({ currentUserId: null }),
    model({ gate: { ...openGate, subjectRevision: null } }),
    model({ gate: { ...openGate, subjectRevision: 0 } }),
    model({
      gate: {
        ...openGate,
        permittedDecisions: ["approved", "approved"],
      },
    }),
  ];
  for (const card of cases) {
    assert.ok(card);
    assert.equal(card.state, "unavailable");
    assert.deepEqual(card.permittedDecisions, []);
  }
});

test("a durable ICP confirmation exposes all three typed decisions", () => {
  const card = model({
    gate: {
      ...openGate,
      kind: "icp_confirmation",
      subjectRef: "icp_spec:independent-neurosurgery-practices:v1",
      subjectSnapshot: { icp_key: "independent_neurosurgery_practices" },
      maxSpendCents: null,
      currency: null,
    },
  });
  assert.ok(card);
  assert.equal(card.title, "Review your ideal customer profile");
  assert.equal(card.state, "requested");
  assert.equal(
    card.summary,
    `Independent Neurosurgery Practices · Version ${openGate.subjectRevision}`,
  );
  assert.deepEqual(card.permittedDecisions, ["approved", "rejected", "revised"]);
});

test("gate presentation copy is human-facing while authority stays internal", () => {
  const card = model({
    gate: {
      ...openGate,
      kind: "icp_confirmation",
      subjectRef: `icp-spec:ws-demo:${openGate.gateId}:v1`,
      subjectSnapshot: { icp_key: openGate.gateId },
      maxSpendCents: null,
      currency: null,
    },
  });
  assert.ok(card);
  assert.equal(card.title, "Review your ideal customer profile");
  assert.equal(
    card.summary,
    `Ideal customer profile · Version ${openGate.subjectRevision}`,
  );
  assert.equal(gateDecisionCopy(card.kind, "approved"), "Approve profile");
  assert.equal(gateDecisionCopy(card.kind, "rejected"), "Reject proposal");
  assert.equal(gateDecisionCopy(card.kind, "revised"), "Request changes");
  assert.equal(
    gateDecisionCopy(card.kind, "approved", true),
    "Profile approved",
  );
  assert.equal(`${card.title} ${card.summary}`.includes(openGate.gateId), false);
});

test("unsupported durable kinds are non-interactive recovery notices", () => {
  const card = model({ gate: { ...openGate, kind: "plan_approval" } });
  assert.ok(card);
  assert.equal(card.state, "unavailable");
  assert.equal(card.title, "Human action required");
  assert.equal(card.recovery?.kind, "request_new_gate");
  assert.deepEqual(card.permittedDecisions, []);
});

test("answered gates stay in history from their immutable receipt", () => {
  const answered: ChatGate = {
    ...openGate,
    answer: {
      turnId: "t2",
      actionRef: "turn-action:t2",
      decision: "approved",
      expectedSubjectSha256: openGate.expectedSubjectSha256,
      decisionPayload: {},
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
  const card = model({ gate: answered });
  assert.ok(card);
  assert.equal(card.state, "responded");
  assert.equal(card.decision, "approved");
  assert.equal(card.answeredByUserId, "usr_demo");
  assert.equal(card.launches.length, 1);
});

test("a revised answer projects its immutable requested changes", () => {
  const revisedGate: ChatGate = {
    ...openGate,
    kind: "icp_confirmation",
    answer: {
      turnId: "t3",
      actionRef: "turn-action:t3",
      decision: "revised",
      expectedSubjectSha256: openGate.expectedSubjectSha256,
      decisionPayload: { revision_request: "Focus on multi-site practices." },
      selectedOptionRef: null,
      answeredByUserId: "usr_demo",
      answeredAt: "2026-08-09T11:12:00Z",
    },
  };
  const card = model({ gate: revisedGate });
  assert.ok(card);
  assert.equal(card.state, "denied");
  assert.equal(card.decision, "revised");
  assert.equal(card.revisionRequest, "Focus on multi-site practices.");
  assert.deepEqual(gateAnswerDisplay(revisedGate), {
    detail: "Focus on multi-site practices.",
    label: "Changes requested",
  });
});

test("a rejected gate is denied — closed, recorded, never re-answerable", () => {
  const card = model({
    gate: {
      ...openGate,
      answer: {
        turnId: "t3-rejected",
        actionRef: "turn-action:t3-rejected",
        decision: "rejected",
        expectedSubjectSha256: openGate.expectedSubjectSha256,
        decisionPayload: {},
        selectedOptionRef: null,
        answeredByUserId: "usr_demo",
        answeredAt: "2026-08-09T11:12:00Z",
      },
    },
  });
  assert.ok(card);
  assert.equal(card.state, "denied");
  assert.equal(card.decision, "rejected");
});

test("a corrupt answer digest cannot masquerade as an immutable receipt", () => {
  const card = model({
    gate: {
      ...openGate,
      answer: {
        turnId: "t4",
        actionRef: "turn-action:t4",
        decision: "approved",
        expectedSubjectSha256: "f".repeat(64),
        decisionPayload: {},
        selectedOptionRef: null,
        answeredByUserId: "usr_demo",
        answeredAt: "2026-08-09T11:14:00Z",
      },
    },
  });
  assert.ok(card);
  assert.equal(card.state, "unavailable");
  assert.match(card.unavailableReason ?? "", /saved decision/);
});

test("a receipt recorded for someone other than the addressee is rejected", () => {
  const card = model({
    gate: {
      ...openGate,
      answer: {
        turnId: "t5",
        actionRef: "turn-action:t5",
        decision: "approved",
        expectedSubjectSha256: openGate.expectedSubjectSha256,
        decisionPayload: {},
        selectedOptionRef: null,
        answeredByUserId: "usr_other",
        answeredAt: "2026-08-09T11:15:00Z",
      },
    },
  });
  assert.ok(card);
  assert.equal(card.state, "unavailable");
  assert.match(card.unavailableReason ?? "", /saved decision/);
});

test("answer payloads preserve the gate digest and enforce typed ICP revision text", () => {
  const icp = model({
    gate: {
      ...openGate,
      kind: "icp_confirmation",
      maxSpendCents: null,
      currency: null,
    },
  });
  assert.ok(icp);
  assert.deepEqual(
    gateAnswerResponse(icp, {
      kind: "icp_revision",
      decision: "revised",
      revisionRequest: "  Narrow to multi-site practices.  ",
    }),
    {
      gateId: openGate.gateId,
      decision: "revised",
      expectedSubjectSha256: openGate.expectedSubjectSha256,
      expectedEstimatedCostCents: null,
      revisionRequest: "Narrow to multi-site practices.",
    },
  );
  assert.deepEqual(
    gateAnswerResponse(icp, { kind: "decision", decision: "rejected" }),
    {
      gateId: openGate.gateId,
      decision: "rejected",
      expectedSubjectSha256: openGate.expectedSubjectSha256,
      expectedEstimatedCostCents: null,
    },
  );
  assert.throws(
    () =>
      gateAnswerResponse(icp, {
        kind: "icp_revision",
        decision: "revised",
        revisionRequest: "   ",
      }),
    /Describe/,
  );
  assert.throws(
    () => gateAnswerResponse(icp, { kind: "decision", decision: "revised" }),
    /Describe/,
  );
  assert.throws(
    () =>
      gateAnswerResponse(
        { ...icp, kind: "directive_confirmation" },
        {
          kind: "icp_revision",
          decision: "revised",
          revisionRequest: "unexpected",
        },
      ),
    /requesting a revision/,
  );
});

test("stale answers request regeneration while concurrent answers request a refresh", () => {
  assert.equal(
    gateAuthorityFailure("GATE_SUBJECT_STALE", "The ICP changed.").recovery?.kind,
    "request_new_gate",
  );
  assert.equal(
    gateAuthorityFailure("GATE_ALREADY_ANSWERED", "Already answered.").recovery?.kind,
    "retry_gate_read",
  );
  assert.equal(
    gateAuthorityFailure("GATE_FORBIDDEN", "Addressed elsewhere.").recovery,
    null,
  );
});

test("malformed durable digests and gate ids fail at the repository seam", () => {
  assert.throws(() =>
    ChatGateListResponseSchema.parse({
      data: [{ ...fixtureGates[0], expected_subject_sha256: "not-a-digest" }],
    }),
  );
  assert.throws(() =>
    ChatGateListResponseSchema.parse({
      data: [{ ...fixtureGates[0], gate_id: "human_only" }],
    }),
  );
});

test("no gate and no part produces no card", () => {
  assert.equal(model({ gate: null, gatePart: null }), null);
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
  const card = model({ gate });
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
          expected_subject_sha256: fixtureGates[0]?.expected_subject_sha256,
          decision_payload: {},
          selected_option_ref: "prd_phone",
          answered_by_user_id: "usr_demo",
          answered_at: "2026-08-15T12:00:00Z",
        },
      },
    ],
  });
  const card = model({ gate });
  assert.ok(card);
  assert.equal(card.state, "responded");
  assert.equal(card.selectedProductId, "prd_phone");
  assert.equal(card.selectedProductName, "AI Phone Agents");
  assert.deepEqual(gateAnswerDisplay(gate), {
    detail: "AI Phone Agents",
    label: "Product selected",
  });
});

test("a product decision carries the dedicated selected product field", () => {
  const [gate] = ChatGateListResponseSchema.parse({
    data: [
      {
        ...fixtureGates[0],
        kind: "product_selection",
        permitted_decisions: ["approved", "rejected"],
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
      },
    ],
  });
  const card = model({ gate });
  assert.ok(card);
  assert.deepEqual(
    gateAnswerResponse(card, {
      kind: "product_selection",
      decision: "approved",
      selectedProductId: "prd_phone",
    }),
    {
      gateId: gate.gateId,
      decision: "approved",
      expectedSubjectSha256: gate.expectedSubjectSha256,
      expectedEstimatedCostCents: null,
      selectedProductId: "prd_phone",
    },
  );
  assert.throws(
    () => gateAnswerResponse(card, { kind: "decision", decision: "approved" }),
    /Choose one/,
  );
});

/**
 * The set-valued product gate (O6 ruling D10).
 *
 * A project buys *products*, plural: the gate presents this brand's whole
 * catalog and the human checks the ones this project sells. The snapshot is the
 * immutable subject, so the card's options, its pre-checks and its receipt all
 * come from that one payload — never from a live catalog read.
 */

const PRODUCT_SET_PRODUCTS = [
  {
    product_id: "prd_phone",
    name: "AI Phone Agents",
    short_description: "Healthcare call and scheduling automation",
    aliases: ["Insight Voice"],
    status: "active",
    resolution_state: "model_matched",
    reconcile_confidence: "high",
    reconcile_reason: null,
    offering_kind: "product",
    family: "Voice",
    lifecycle: "active",
    official_url: "https://example.test/phone",
  },
  {
    product_id: "prd_intake",
    name: "Patient Intake",
    // A product row the catalog does not describe is honestly blank.
    short_description: "",
    aliases: [],
    status: "active",
    resolution_state: "model_unsure",
    reconcile_confidence: "low",
    reconcile_reason: "Name overlaps the phone offering",
    offering_kind: "platform",
    family: null,
    lifecycle: "beta",
    official_url: null,
  },
  {
    product_id: "prd_fax",
    name: "Legacy Fax",
    short_description: "Retired fax bridge",
    aliases: [],
    status: "archived",
    resolution_state: null,
    reconcile_confidence: null,
    reconcile_reason: null,
    offering_kind: "service",
    family: null,
    lifecycle: "retired",
    official_url: null,
  },
] as const;

function productSetGate(overrides: Record<string, unknown> = {}): ChatGate {
  const {
    snapshot = {},
    ...gateOverrides
  } = overrides as { snapshot?: Record<string, unknown> };
  const [gate] = ChatGateListResponseSchema.parse({
    data: [
      {
        ...fixtureGates[0],
        kind: "product_set_selection",
        max_spend_cents: null,
        currency: null,
        subject_ref: "brand-product-catalog:brd_demo:doc-catalog",
        subject_revision: 3,
        permitted_decisions: ["approved", "rejected", "revised"],
        subject_snapshot: {
          brand_id: "brd_demo",
          catalog_document_id: "doc-catalog",
          catalog_version: 3,
          products: PRODUCT_SET_PRODUCTS,
          omitted_count: 1,
          current_selection: null,
          suggested_product_ids: ["prd_phone"],
          ...snapshot,
        },
        ...gateOverrides,
      },
    ],
  });
  return gate;
}

test("a product-set gate derives every option, the suggested pre-check and the duplicate flag", () => {
  const card = model({ gate: productSetGate() });
  assert.ok(card);
  assert.equal(card.kind, "product_set_selection");
  assert.equal(card.title, "Choose this project's products");
  assert.ok(card.productSet);
  assert.deepEqual(
    card.productSet.options.map((option) => option.productId),
    ["prd_phone", "prd_intake", "prd_fax"],
  );
  // Archived rows are shown but never selectable, so the choosable set is two.
  assert.deepEqual(
    card.productSet.options
      .filter((option) => option.status !== "archived")
      .map((option) => option.productId),
    ["prd_phone", "prd_intake"],
  );
  assert.deepEqual(card.productSet.preselectedIds, ["prd_phone"]);
  assert.equal(card.productSet.currentSelectionVersion, null);
  assert.deepEqual(card.productSet.selectedIds, []);
  assert.equal(card.productSet.options[0]?.offeringKind, "product");
  assert.equal(card.productSet.options[0]?.family, "Voice");
  assert.equal(card.productSet.options[0]?.lifecycle, "active");
  assert.equal(card.productSet.options[0]?.officialUrl, "https://example.test/phone");
  assert.equal(card.productSet.options[0]?.possibleDuplicate, false);
  assert.equal(card.productSet.options[1]?.possibleDuplicate, true);
  assert.equal(
    card.productSet.options[1]?.duplicateReason,
    "Name overlaps the phone offering",
  );
  assert.equal(card.summary, "3 products available · 1 pre-checked");
});

test("a saved project selection is the pre-check, not the suggestion", () => {
  const card = model({
    gate: productSetGate({
      snapshot: {
        current_selection: { selection_version: 2, product_ids: ["prd_intake"] },
      },
    }),
  });
  assert.ok(card?.productSet);
  assert.deepEqual(card.productSet.preselectedIds, ["prd_intake"]);
  assert.equal(card.productSet.currentSelectionVersion, 2);
});

test("a product-set decision refuses an empty or archived choice and carries the id list", () => {
  const gate = productSetGate();
  const card = model({ gate });
  assert.ok(card);
  assert.throws(
    () =>
      gateAnswerResponse(card, {
        kind: "product_set_selection",
        decision: "approved",
        selectedProductIds: [],
      }),
    /Choose at least one of the products shown before continuing\./,
  );
  assert.throws(
    () =>
      gateAnswerResponse(card, {
        kind: "product_set_selection",
        decision: "approved",
        selectedProductIds: ["prd_fax"],
      }),
    /no longer available/,
  );
  assert.throws(
    () => gateAnswerResponse(card, { kind: "decision", decision: "approved" }),
    /Choose at least one of the products shown before continuing\./,
  );
  assert.deepEqual(
    gateAnswerResponse(card, {
      kind: "product_set_selection",
      decision: "approved",
      selectedProductIds: ["prd_phone", "prd_intake"],
    }),
    {
      gateId: gate.gateId,
      decision: "approved",
      expectedSubjectSha256: gate.expectedSubjectSha256,
      expectedEstimatedCostCents: null,
      selectedProductIds: ["prd_phone", "prd_intake"],
    },
  );
});

test("an answered product-set gate keeps the chosen ids and names", () => {
  const gate = productSetGate({
    answer: {
      turn_id: "turn-product-set",
      action_ref: "turn-action:turn-product-set",
      decision: "approved",
      expected_subject_sha256: fixtureGates[0]?.expected_subject_sha256,
      decision_payload: { selected_option_refs: ["prd_phone", "prd_intake"] },
      selected_option_ref: null,
      answered_by_user_id: "usr_demo",
      answered_at: "2026-09-09T12:00:00Z",
    },
  });
  const card = model({ gate });
  assert.ok(card?.productSet);
  assert.equal(card.state, "responded");
  assert.deepEqual(card.productSet.selectedIds, ["prd_phone", "prd_intake"]);
  assert.equal(card.summary, "AI Phone Agents, Patient Intake");
  assert.deepEqual(gateAnswerDisplay(gate), {
    detail: "AI Phone Agents, Patient Intake",
    label: "Products selected",
  });
});

// --- the CRM write permission card (CRM integration Phase 2, Task 9) ------

const CRM_PROPOSAL = "11111111-2222-4333-8444-555555555555";
const CRM_WRITE = "00000000-0000-4000-8000-000000000001";

function crmGate(overrides: Partial<ChatGate> = {}): ChatGate {
  return {
    ...openGate,
    kind: "crm_write_permission",
    subjectRef: `crm_write_proposal:${CRM_PROPOSAL}`,
    // A write card has no revision and no amount.
    subjectRevision: null,
    maxSpendCents: null,
    currency: null,
    permittedDecisions: ["approved", "rejected"],
    addresseeUserId: "usr_someone_else",
    subjectSnapshot: {
      crm: "hubspot",
      project_name: "Q4",
      title: "Clue wants to update HubSpot",
      description: 'For "Q4". Nothing is sent until you allow it.',
      groups: [
        {
          kind: "create_contact",
          object: "contact",
          field: null,
          field_label: null,
          list_ref: null,
          title: "Create 1 contact",
          count: 1,
          value_summary: null,
          reason: "New buyer.",
          records: [{ write_id: CRM_WRITE, record_ref: null, name: "ana@acme.com" }],
          scope_key: "hubspot:create_contact:contact",
          always_allow: "creating contacts",
          selected: true,
        },
      ],
      overwrites_heading: null,
      overwrites: [],
      standing_permissions: [
        { scope_key: "hubspot:create_contact:contact", phrase: "creating contacts", selected: false },
      ],
      allow_count: 1,
      caption: "Any member of this workspace can answer.",
    },
    ...overrides,
  };
}

test("any workspace member can answer a CRM write card, which has no revision", () => {
  const card = model({ gate: crmGate() });
  assert.ok(card);
  assert.equal(card.state, "requested");
  assert.equal(card.crmProposalId, CRM_PROPOSAL);
  assert.equal(card.crmWrite?.title, "Clue wants to update HubSpot");
  assert.deepEqual(
    gateAnswerResponse(card, {
      kind: "crm_write",
      decision: "approved",
      answer: { selected_write_ids: [CRM_WRITE], always_allow: ["hubspot:create_contact:contact"] },
    }),
    {
      gateId: openGate.gateId,
      decision: "approved",
      expectedSubjectSha256: openGate.expectedSubjectSha256,
      expectedEstimatedCostCents: null,
      crmWrite: {
        selected_write_ids: [CRM_WRITE],
        always_allow: ["hubspot:create_contact:contact"],
      },
    },
  );
  // "Don't allow" sends nothing but the decision.
  assert.deepEqual(gateAnswerResponse(card, { kind: "decision", decision: "rejected" }), {
    gateId: openGate.gateId,
    decision: "rejected",
    expectedSubjectSha256: openGate.expectedSubjectSha256,
    expectedEstimatedCostCents: null,
  });
  assert.throws(() =>
    gateAnswerResponse(card, {
      kind: "crm_write",
      decision: "approved",
      answer: { selected_write_ids: [], always_allow: [] },
    }),
  );
});

test("a CRM write card answered by another member is a receipt, not a notice", () => {
  const card = model({
    gate: crmGate({
      answer: {
        turnId: "turn-answer",
        actionRef: "turn-action:x",
        decision: "approved",
        expectedSubjectSha256: openGate.expectedSubjectSha256,
        decisionPayload: { selected_write_ids: [CRM_WRITE], always_allow: [] },
        selectedOptionRef: null,
        answeredByUserId: "usr_demo",
        answeredAt: "2026-10-22T14:02:00Z",
      },
    }),
  });
  assert.equal(card?.state, "responded");
});

test("a replaced CRM write card reads as withdrawn, never as requested", () => {
  const card = model({ gate: crmGate({ withdrawn: true }) });
  assert.equal(card?.state, "withdrawn");
  assert.ok(card?.crmWrite);
});

test("a refused CRM answer keeps the card and says why", () => {
  const card = model({
    gate: crmGate(),
    authorityFailure: { reason: "Tick at least one change to allow.", recovery: null },
  });
  assert.equal(card?.state, "requested");
  assert.equal(card?.problem, "Tick at least one change to allow.");
});
