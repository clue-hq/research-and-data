import assert from "node:assert/strict";
import test from "node:test";
import type { ChatToolPart } from "./chat-parts";
import {
  profileDisplayName,
  toolPresentation,
} from "./chat-tool-presentation";

const GATE_ID = "6fae9039-bbaf-50ff-81bc-b0ba66155f6c";
const USER_ID = "usr_24ef6554bea84ec8a32e4f9f0aae4b0e";
const WORKSPACE_ID = "ws_fixture_insight_health_browser";
const DIGEST = "90f10d1e7105b20e53fabc4278dc2c10d70cf1588b791f00f8ca6ed44b7055b5";

function part(
  toolName: string,
  output: Record<string, unknown> | null,
  overrides: Partial<ChatToolPart> = {},
): ChatToolPart {
  return {
    kind: "tool",
    partId: "tool-part",
    revision: 2,
    state: "output-available",
    toolName,
    toolVersion: "2",
    toolCallId: "call_internal_123",
    nodeKey: "agent_internal_node",
    operationId: "640ddcf7-5001-5441-b977-9065feaee109",
    input: null,
    output,
    errorCode: null,
    errorReasons: [],
    ...overrides,
  };
}

function visibleText(value: ReturnType<typeof toolPresentation>): string {
  return [
    value.label,
    ...value.rows.flatMap((row) => [row.label, row.value]),
    value.failureMessage,
  ]
    .filter((item): item is string => item !== null)
    .join(" ");
}

test("readiness shows business metrics without exposing receipt metadata", () => {
  const presentation = toolPresentation(
    part("evaluate_stage0_readiness", {
      operation_id: "640ddcf7-5001-5441-b977-9065feaee109",
      artifact_refs: [{ sha256: DIGEST, workspace_id: WORKSPACE_ID }],
      reference_values: {
        verdict: "ready",
        coverage_ratio: 0.7777777777,
        verified_claims: 7,
        available_field_keys: [
          "client.product",
          "client.value_prop",
          "client.differentiator",
          "client.unknown_internal_field",
        ],
        readiness_decision_id: GATE_ID,
        readiness_policy_version: 1,
      },
    }),
  );

  assert.equal(presentation.label, "Check profile readiness");
  assert.deepEqual(presentation.rows, [
    { label: "Result", value: "Ready to create a profile" },
    { label: "Information available", value: "78%" },
    { label: "Verified facts", value: "7" },
    {
      label: "Known details",
      value: "product details, value proposition, what makes the product different",
    },
  ]);
  const text = visibleText(presentation);
  assert.doesNotMatch(text, /640ddcf7|90f10d1e|ws_fixture|readiness_decision|client\./);
});

test("profile synthesis names the proposal but withholds tenant and decision ids", () => {
  const presentation = toolPresentation(
    part("synthesize_icps", {
      artifact_refs: [{ sha256: DIGEST }],
      reference_values: {
        icp_specs: [
          {
            status: "draft",
            icp_key: "independent_multisite_neurosurgery_spine_practices",
            icp_version: 1,
            workspace_id: WORKSPACE_ID,
          },
        ],
        readiness_decision_id: GATE_ID,
      },
    }),
  );

  assert.equal(presentation.label, "Create an ideal customer profile proposal");
  assert.deepEqual(presentation.rows, [
    {
      label: "Proposal",
      value: "Independent Multisite Neurosurgery Spine Practices · Version 1",
    },
  ]);
  assert.doesNotMatch(visibleText(presentation), /ws_fixture|6fae9039|90f10d1e/);
});

test("ICP authoring and persona requests read as operator work, not tool names", () => {
  const authoring = toolPresentation(
    part("author_icp_document", {
      reference_values: {
        icp_key: "independent_multisite_neurosurgery_spine_practices",
        icp_version: 2,
        workspace_id: WORKSPACE_ID,
        document_id: GATE_ID,
      },
    }),
  );
  assert.equal(authoring.label, "Draft an ideal customer profile");
  assert.deepEqual(authoring.rows, []);
  assert.doesNotMatch(visibleText(authoring), /ws_fixture|6fae9039/);

  const personas = toolPresentation(
    part("request_persona_synthesis", {
      reference_values: { run_id: GATE_ID, kind: "personas", status: "queued" },
    }),
  );
  assert.equal(personas.label, "Write the buyer personas");
  assert.deepEqual(personas.rows, []);
  assert.doesNotMatch(visibleText(personas), /6fae9039|queued/);
});

test("writing the project plan reads as operator work, not a tool name", () => {
  const presentation = toolPresentation(
    part("write_project_document", {
      reference_values: {
        document_id: GATE_ID,
        document: "plan",
        version: 2,
        workspace_id: WORKSPACE_ID,
      },
    }),
  );

  assert.equal(presentation.label, "Write the project plan");
  assert.deepEqual(presentation.rows, []);
  assert.doesNotMatch(visibleText(presentation), /ws_fixture|6fae9039/);
});

test("the five reads read as reviewing work, not tool names", () => {
  const accounts = toolPresentation(
    part("read_project_accounts", {
      project_id: GATE_ID,
      total: 12,
      accounts: [{ account_entity_id: GATE_ID, name: "Goodman Campbell" }],
    }),
  );
  assert.equal(accounts.label, "Review the project's accounts");

  const research = toolPresentation(
    part("read_account_research", {
      account_entity_id: GATE_ID,
      account_name: "Goodman Campbell",
      section: "overview",
      overview: [],
      claims: [],
      truncated: false,
    }),
  );
  assert.equal(research.label, "Review an account's research");

  const discovery = toolPresentation(
    part("read_discovery_run", {
      run_id: GATE_ID,
      status: "completed",
      asked: 20,
      found: 13,
      candidates: [],
    }),
  );
  assert.equal(discovery.label, "Review the discovery run");

  const claims = toolPresentation(
    part("read_claims", {
      entity_id: GATE_ID,
      entity_kind: "account",
      claims: [],
      total: 0,
      next_offset: null,
      prefixes: [],
    }),
  );
  assert.equal(claims.label, "Query the claims");

  const artifact = toolPresentation(
    part("read_artifact", {
      artifact_id: "doc_matrix",
      kind: "web",
      title: "Matrix",
      status: "ready",
      body_text: "",
      body_truncated: false,
    }),
  );
  assert.equal(artifact.label, "Open an artifact");

  for (const presentation of [accounts, research, discovery, claims, artifact]) {
    assert.deepEqual(presentation.rows, []);
    assert.doesNotMatch(visibleText(presentation), /ws_fixture|6fae9039/);
  }
});

test("gate preparation never exposes gate, user, workspace, ref, or digest values", () => {
  const presentation = toolPresentation(
    part("open_icp_confirmation_gate", {
      operation_id: "185507ba-bfd9-5ed7-b68e-e57fad3d9f01",
      artifact_refs: [{ sha256: DIGEST }],
      reference_values: {
        created: true,
        gate_id: GATE_ID,
        gate_ref: `agent-gate:${GATE_ID}`,
        addressee_user_id: USER_ID,
        expected_subject_sha256: DIGEST,
        subject_ref: {
          icp_key: "independent_neurosurgery_spine_practices",
          icp_version: 1,
          workspace_id: WORKSPACE_ID,
        },
      },
    }),
  );

  assert.deepEqual(presentation.rows, [
    {
      label: "Proposal",
      value: "Independent Neurosurgery Spine Practices · Version 1",
    },
    { label: "Status", value: "Ready for your review" },
  ]);
  const text = visibleText(presentation);
  for (const forbidden of [GATE_ID, USER_ID, WORKSPACE_ID, DIGEST, "agent-gate"]) {
    assert.equal(text.includes(forbidden), false, forbidden);
  }
});

test("unknown tools fail closed to a generic label with no arbitrary wire data", () => {
  const presentation = toolPresentation(
    part("future_governed_operation", {
      customer_facing_guess: "Do not trust this field",
      gate_id: GATE_ID,
      sha256: DIGEST,
    }),
  );
  assert.equal(presentation.label, "Complete a project step");
  assert.deepEqual(presentation.rows, []);
  assert.equal(presentation.failureMessage, null);
});

test("failures use stable human copy rather than backend codes or reasons", () => {
  const presentation = toolPresentation(
    part(
      "open_icp_confirmation_gate",
      { gate_id: GATE_ID, sha256: DIGEST },
      {
        state: "output-error",
        errorCode: "GATE_SUBJECT_STALE",
        errorReasons: [`digest ${DIGEST} did not match gate ${GATE_ID}`],
      },
    ),
  );
  assert.deepEqual(presentation.rows, []);
  assert.equal(
    presentation.failureMessage,
    "This step could not be completed. Ask the assistant to try again.",
  );
  assert.doesNotMatch(visibleText(presentation), /GATE_SUBJECT|90f10d1e|6fae9039/);
});

test("opaque values never become profile names", () => {
  assert.equal(profileDisplayName(GATE_ID), "Ideal customer profile");
  assert.equal(profileDisplayName(DIGEST), "Ideal customer profile");
  assert.equal(profileDisplayName(WORKSPACE_ID), "Ideal customer profile");
});
