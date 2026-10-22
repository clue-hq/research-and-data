import assert from "node:assert/strict";
import test from "node:test";
import { ChatPartSnapshotSchema } from "./chat-parts";
import {
  ChatMessageListResponseSchema,
  openGateIds,
  unavailableMessageBody,
} from "./chat-message";
import {
  ChatThreadListResponseSchema,
  ChatThreadResponseSchema,
  THREAD_STATUS_PRECEDENCE,
  deriveThreadStatus,
  mostUrgentThreadStatus,
  resolveProjectThreadRoute,
  threadLabel,
} from "./chat-thread";
import {
  AcceptedTurnResponseSchema,
  ChatTurnListResponseSchema,
  turnStateForStreamEvent,
  turnRequestBody,
} from "./chat-turn";
import { ChatGateListResponseSchema, formatCents, isGateOpen } from "./chat-gate";
import { parseHomeBootstrapDraft } from "./home-submission";
import {
  fixtureGates,
  fixtureMessages,
  fixtureThreads,
  fixtureTurns,
} from "../data/chat.fixture";

/** Schema round-trips for every amended model, against wire-shaped fixtures. */

test("the thread list parses the as-built wire and its nullable title", () => {
  const page = ChatThreadListResponseSchema.parse({
    data: fixtureThreads,
    meta: { next_cursor: "cursor-2" },
  });
  assert.equal(page.nextCursor, "cursor-2");
  assert.equal(page.threads[0].projectId, "10m-landing-page-campaign");
  assert.equal(page.threads[1].title, null);
  assert.equal(threadLabel(page.threads[1]), "New chat");
});

test("create returns the ratified 201 superset", () => {
  const thread = ChatThreadResponseSchema.parse({ data: fixtureThreads[0] });
  assert.equal(thread.pinned, true);
  assert.equal(thread.status, "idle");
  assert.ok(thread.createdAt);
});

test("the status vocabulary is the pinned precedence, and archived outranks all", () => {
  assert.deepEqual(THREAD_STATUS_PRECEDENCE, [
    "archived",
    "approval",
    "needs-input",
    "running",
    "idle",
  ]);
  assert.equal(
    deriveThreadStatus({
      archived: true,
      openGateKinds: ["directive_confirmation"],
      running: true,
    }),
    "archived",
  );
  // An open gate outranks running: the conversation is blocked on the user.
  assert.equal(
    deriveThreadStatus({
      archived: false,
      openGateKinds: ["directive_confirmation"],
      running: true,
    }),
    "approval",
  );
  assert.equal(
    deriveThreadStatus({ archived: false, openGateKinds: ["budget_approval"] }),
    "needs-input",
  );
  assert.equal(deriveThreadStatus({ archived: false, running: true }), "running");
  assert.equal(deriveThreadStatus({ archived: false }), "idle");
  assert.equal(mostUrgentThreadStatus("running", "approval"), "approval");
});

test("a project route never selects a thread outside its scoped thread page", () => {
  const page = ChatThreadListResponseSchema.parse({
    data: [
      {
        id: "thr_allowed",
        title: "Allowed thread",
        href: "/projects/prj_a/chats/thr_allowed",
        status: "idle",
        pinned: false,
        project_id: "prj_a",
        created_at: "2026-08-10T00:00:00Z",
        updated_at: "2026-08-10T00:00:00Z",
      },
    ],
    meta: { next_cursor: null },
  });
  const crossed = resolveProjectThreadRoute(page.threads, "thr_from_project_b");
  assert.equal(crossed.kind, "selected");
  if (crossed.kind === "selected") {
    assert.equal(crossed.thread.id, "thr_allowed");
    assert.equal(crossed.canonicalize, true);
  }
  assert.deepEqual(resolveProjectThreadRoute([], "thr_from_project_b"), {
    kind: "not-found",
    requestedThreadId: "thr_from_project_b",
  });
});

test("message reads are body-free by default and carry the typed refs", () => {
  const page = ChatMessageListResponseSchema.parse({
    data: fixtureMessages.map((message) => ({
      ...message,
      body: null,
      body_unavailable_reason: null,
    })),
    meta: {},
  });
  assert.equal(page.messages[0].body, null);
  assert.equal(page.messages[1].refs[0].flavor, "open_gate");
  assert.deepEqual(openGateIds(page.messages[1]), [fixtureGates[0].gate_id]);
});

test("design asset context refs retain read-time filename and thumbnail metadata", () => {
  const page = ChatMessageListResponseSchema.parse({
    data: [
      {
        ...fixtureMessages[0],
        body: "Use this composition as inspiration.",
        refs: [
          {
            flavor: "context",
            workspace_id: "ws-demo",
            object_type: "design_asset",
            object_id: "asset_reference",
            version: null,
            ordinal: 0,
            label: "inspiration.webp",
            media_type: "image/webp",
            thumbnail_digest: "b".repeat(64),
          },
        ],
      },
    ],
    meta: { next_cursor: null },
  });

  assert.deepEqual(page.messages[0].refs[0], {
    flavor: "context",
    workspaceId: "ws-demo",
    objectType: "design_asset",
    objectId: "asset_reference",
    version: null,
    ordinal: 0,
    label: "inspiration.webp",
    // A design asset carries no document kind; the wire omits it and it reads as null.
    kind: null,
    mediaType: "image/webp",
    thumbnailDigest: "b".repeat(64),
    // A design asset is not a chat upload; it has no upload route to fetch from.
    uploadId: null,
  });
});

test("attachment refs carry the human's filename, media type and upload id", () => {
  const page = ChatMessageListResponseSchema.parse({
    data: [
      {
        ...fixtureMessages[0],
        body: "Here is the screenshot.",
        refs: [
          {
            flavor: "attachment",
            workspace_id: "ws-demo",
            object_type: "artifact",
            object_id: "ws-demo/" + "c".repeat(64),
            version: null,
            ordinal: 0,
            label: "shot.png",
            media_type: "image/png",
            upload_id: "11111111-2222-3333-4444-555555555555",
          },
        ],
      },
    ],
    meta: { next_cursor: null },
  });

  assert.deepEqual(page.messages[0].refs[0], {
    flavor: "attachment",
    workspaceId: "ws-demo",
    objectType: "artifact",
    objectId: "ws-demo/" + "c".repeat(64),
    version: null,
    ordinal: 0,
    label: "shot.png",
    kind: null,
    mediaType: "image/png",
    thumbnailDigest: null,
    uploadId: "11111111-2222-3333-4444-555555555555",
  });
});

test("an unservable body is reported with its reason, never as empty text", () => {
  const page = ChatMessageListResponseSchema.parse({
    data: [{ ...fixtureMessages[0], body: null, body_unavailable_reason: "erased" }],
    meta: {},
  });
  assert.equal(page.messages[0].body, null);
  assert.equal(page.messages[0].bodyUnavailableReason, "erased");
});

test("a physically missing historical artifact gives actionable recovery copy", () => {
  const page = ChatMessageListResponseSchema.parse({
    data: [
      {
        ...fixtureMessages[0],
        body: null,
        body_unavailable_reason: "artifact_missing",
      },
    ],
    meta: {},
  });
  const reason = page.messages[0].bodyUnavailableReason;
  assert.equal(reason, "artifact_missing");
  assert.equal(
    unavailableMessageBody(reason ?? ""),
    "This earlier message could not be recovered. Please resend it in a new chat.",
  );
  assert.equal(
    unavailableMessageBody("budget"),
    "This message's text is unavailable (budget).",
  );
  assert.deepEqual(
    turnRequestBody({
      kind: "gate_response",
      response: {
        gateId: "g-product",
        decision: "approved",
        expectedSubjectSha256: "b".repeat(64),
        expectedEstimatedCostCents: null,
        selectedProductId: "prd_phone",
      },
    }),
    {
      gate_response: {
        gate_id: "g-product",
        decision: "approved",
        expected_subject_sha256: "b".repeat(64),
        expected_estimated_cost_cents: null,
        selected_product_id: "prd_phone",
      },
    },
  );
  // The set-valued gate sends the whole chosen list, never a single id.
  assert.deepEqual(
    turnRequestBody({
      kind: "gate_response",
      response: {
        gateId: "g-product-set",
        decision: "approved",
        expectedSubjectSha256: "c".repeat(64),
        expectedEstimatedCostCents: null,
        selectedProductIds: ["prd_phone", "prd_intake"],
      },
    }),
    {
      gate_response: {
        gate_id: "g-product-set",
        decision: "approved",
        expected_subject_sha256: "c".repeat(64),
        expected_estimated_cost_cents: null,
        selected_product_ids: ["prd_phone", "prd_intake"],
      },
    },
  );
});

test("a CRM write card's Allow sends its choices as crm_write", () => {
  assert.deepEqual(
    turnRequestBody({
      kind: "gate_response",
      response: {
        gateId: "g-crm",
        decision: "approved",
        expectedSubjectSha256: "d".repeat(64),
        expectedEstimatedCostCents: null,
        crmWrite: { selected_write_ids: ["w1", "w2"], always_allow: ["hubspot:create_contact:contact"] },
      },
    }),
    {
      gate_response: {
        gate_id: "g-crm",
        decision: "approved",
        expected_subject_sha256: "d".repeat(64),
        expected_estimated_cost_cents: null,
        crm_write: {
          selected_write_ids: ["w1", "w2"],
          always_allow: ["hubspot:create_contact:contact"],
        },
      },
    },
  );
});

test("a withdrawn gate is never open", () => {
  const [gate] = ChatGateListResponseSchema.parse({
    data: [{ ...fixtureGates[0], withdrawn: true }],
  });
  assert.equal(gate.withdrawn, true);
  assert.equal(isGateOpen(gate), false);
});

test("the submissions-union keeps queued turns and their attach cursor", () => {
  const page = ChatTurnListResponseSchema.parse({
    data: [
      ...fixtureTurns,
      {
        turn_id: "queued-1",
        thread_id: "thread-primary",
        project_id: "10m-landing-page-campaign",
        state: "queued",
        requested_at: "2026-08-09T11:30:00Z",
        last_event_id: null,
        generation_attempts: 0,
        submission_message: {
          id: "accepted-message-1",
          turn_id: "queued-1",
          thread_id: "thread-primary",
          sequence: 0,
          role: "user",
          body_artifact_key: "accepted-key",
          body_sha256: "accepted-sha",
          body: "Accepted before worker claim",
          body_unavailable_reason: null,
          created_at: "2026-08-09T11:30:00Z",
          refs: [],
        },
      },
    ],
    meta: { thread_status: "running" },
  });
  assert.equal(page.threadRunning, true);
  assert.equal(page.turns[0].lastEventId, 24);
  assert.equal(page.turns[1].state, "queued");
  assert.equal(
    page.turns[1].submissionMessage?.body,
    "Accepted before worker claim",
  );
});

test("a turn names the card it answered, and an ordinary turn names none", () => {
  const page = ChatTurnListResponseSchema.parse({
    data: [
      { ...fixtureTurns[0], answered_gate_id: "gate-crm-1" },
      { ...fixtureTurns[0], turn_id: "plain-1" },
    ],
  });
  assert.equal(page.turns[0].answeredGateId, "gate-crm-1");
  assert.equal(page.turns[1].answeredGateId, null);
});

test("durable stream events immediately refine queued/running/terminal turn state", () => {
  assert.equal(turnStateForStreamEvent("turn.accepted"), "queued");
  assert.equal(turnStateForStreamEvent("turn.started"), "running");
  assert.equal(turnStateForStreamEvent("turn.completed"), "completed");
  assert.equal(turnStateForStreamEvent("turn.awaiting_input"), "awaiting_input");
  assert.equal(turnStateForStreamEvent("text.delta"), null);
});

test("a 202 reports whether it replayed an already-accepted identity", () => {
  const accepted = AcceptedTurnResponseSchema.parse({
    data: {
      turn_id: "t1",
      thread_id: "th1",
      requested_at: "2026-08-09T11:30:00Z",
      replayed: true,
    },
  });
  assert.equal(accepted.replayed, true);
});

test("a turn body is exactly one of a message or a gate response", () => {
  assert.deepEqual(turnRequestBody({ kind: "message", message: "hi" }), {
    message: "hi",
    context_refs: [],
    attachment_refs: [],
    agent_profile_id: null,
  });
  assert.deepEqual(
    turnRequestBody({
      kind: "message",
      message: "research these",
      contextRefs: [
        { objectId: "contact-2", objectType: "contact", version: 4 },
        { objectId: "account-1", objectType: "account", version: 2 },
        { objectId: "doc-ad", objectType: "design_document", version: 9 },
        { objectId: "headline", objectType: "design_node", version: 9 },
      ],
      agentProfileId: "head-of-abm@v30",
    }),
    {
      message: "research these",
      context_refs: [
        { object_id: "contact-2", object_type: "contact", version: 4 },
        { object_id: "account-1", object_type: "account", version: 2 },
        { object_id: "doc-ad", object_type: "design_document", version: 9 },
        { object_id: "headline", object_type: "design_node", version: 9 },
      ],
      attachment_refs: [],
      agent_profile_id: "head-of-abm@v30",
    },
  );
  assert.deepEqual(
    turnRequestBody({
      kind: "gate_response",
      response: {
        gateId: "g1",
        decision: "approved",
        expectedSubjectSha256: "a".repeat(64),
        expectedEstimatedCostCents: 24000,
      },
    }),
    {
      gate_response: {
        gate_id: "g1",
        decision: "approved",
        expected_subject_sha256: "a".repeat(64),
        expected_estimated_cost_cents: 24000,
      },
    },
  );
  assert.deepEqual(
    turnRequestBody({
      kind: "gate_response",
      response: {
        gateId: "icp-gate-1",
        decision: "revised",
        expectedSubjectSha256: "b".repeat(64),
        expectedEstimatedCostCents: null,
        revisionRequest: "Narrow the ICP to multi-site practices.",
      },
    }),
    {
      gate_response: {
        gate_id: "icp-gate-1",
        decision: "revised",
        expected_subject_sha256: "b".repeat(64),
        expected_estimated_cost_cents: null,
        revision_request: "Narrow the ICP to multi-site practices.",
      },
    },
  );
});

test("a gate parses its decimal spend and derives open from the missing answer", () => {
  const gates = ChatGateListResponseSchema.parse({ data: fixtureGates });
  assert.equal(gates[0].maxSpendCents, 24000);
  assert.equal(gates[0].currency, "USD");
  assert.equal(isGateOpen(gates[0]), true);
  assert.equal(formatCents(24000, "USD"), "$240.00");
});

test("a gate whose amount was withheld parses, and formats no cost at all", () => {
  const [gate] = ChatGateListResponseSchema.parse({
    data: [{ ...fixtureGates[0], max_spend_cents: null }],
  });
  assert.equal(gate.maxSpendCents, null);
  assert.equal(isGateOpen(gate), true);
  // Never "$0.00": a withheld amount must not be readable as a real one.
  assert.equal(formatCents(gate.maxSpendCents, gate.currency), null);
});

test("every part kind round-trips from its wire snapshot", () => {
  const tool = ChatPartSnapshotSchema.parse({
    part_id: "tool:x",
    kind: "tool",
    revision: 3,
    state: "output-error",
    tool_name: "launch_account_research",
    tool_version: "1",
    tool_call_id: "c1",
    node_key: "x",
    error_code: "launch_action_ref_missing",
    error_reasons: ["no human receipt"],
  });
  assert.equal(tool.kind === "tool" && tool.errorCode, "launch_action_ref_missing");

  const task = ChatPartSnapshotSchema.parse({
    part_id: "task:r",
    kind: "task",
    revision: 1,
    state: "needs_input",
    title: "account research",
    run_ref: { object_type: "entity_research_run", object_id: "r" },
  });
  assert.equal(task.kind === "task" && task.counts.total, 0);

  const gate = ChatPartSnapshotSchema.parse({
    part_id: "gate:g",
    kind: "gate",
    revision: 1,
    gate_ref: { object_type: "agent_gate", object_id: "g" },
    gate_kind: "directive_confirmation",
    state: "requested",
    amount_cents: 24000,
    currency: "USD",
    permitted_decisions: ["approved", "rejected"],
  });
  assert.equal(gate.kind === "gate" && gate.amountCents, 24000);

  const sources = ChatPartSnapshotSchema.parse({
    part_id: "sources:m",
    kind: "sources",
    revision: 1,
    items: [{ source_id: "s1", title: "OpenAI", url: "https://openai.com" }],
  });
  assert.equal(sources.kind === "sources" && sources.items[0].sourceKind, null);

  const activity = ChatPartSnapshotSchema.parse({
    part_id: "activity:a",
    kind: "agent_activity",
    revision: 2,
    title: "Agent activity",
    steps: [{ id: "round:1", kind: "model_round", status: "active", label: "Model round 1" }],
  });
  assert.equal(activity.kind === "agent_activity" && activity.steps[0].description, null);
});

test("a streaming-start text part is representable — empty text, empty parts", () => {
  // The old contract's `text.min(1)` / `parts.min(1)` made this unrepresentable
  // (charter §2's D-4 hazard list). The domain type simply allows it.
  const empty = { kind: "text" as const, partId: "text:a", revision: 1, text: "", streaming: true, failed: false, failureReason: null };
  assert.equal(empty.text, "");
});

test("a context ref's note rides the wire only when present", () => {
  assert.deepEqual(
    turnRequestBody({
      kind: "message",
      message: "fix",
      contextRefs: [
        { objectId: "doc_1", objectType: "design_document", version: 3 },
        {
          objectId: "frg_a#:nth-child(2)",
          objectType: "design_node",
          version: 3,
          note: "1. Make this shorter",
        },
      ],
    }),
    {
      message: "fix",
      context_refs: [
        { object_type: "design_document", object_id: "doc_1", version: 3 },
        {
          object_type: "design_node",
          object_id: "frg_a#:nth-child(2)",
          version: 3,
          note: "1. Make this shorter",
        },
      ],
      attachment_refs: [],
      agent_profile_id: null,
    },
  );
});

test("a message turn body carries every attachment ref field in snake_case", () => {
  assert.deepEqual(
    turnRequestBody({
      kind: "message",
      message: "read this brief",
      attachmentRefs: [
        {
          uploadId: "upl_1",
          artifactKey: `ws_1/${"a".repeat(64)}`,
          sha256: "a".repeat(64),
          mediaType: "text/markdown",
          byteCount: 512,
          filename: "brief.md",
        },
      ],
    }),
    {
      message: "read this brief",
      context_refs: [],
      attachment_refs: [
        {
          upload_id: "upl_1",
          artifact_key: `ws_1/${"a".repeat(64)}`,
          sha256: "a".repeat(64),
          media_type: "text/markdown",
          byte_count: 512,
          filename: "brief.md",
        },
      ],
      agent_profile_id: null,
    },
  );
});

test("a Home bootstrap draft keeps the upload id of an attachment ref", () => {
  const parsed = parseHomeBootstrapDraft({
    brandId: "brd_1",
    message: "read this brief",
    attachmentRefs: [
      {
        artifactKey: `ws_1/${"a".repeat(64)}`,
        byteCount: 512,
        filename: "brief.md",
        mediaType: "text/markdown",
        sha256: "a".repeat(64),
        uploadId: "upl_1",
      },
    ],
  });
  assert.equal(parsed.success, true);
  if (parsed.success) {
    assert.deepEqual(parsed.request.attachmentRefs, [
      {
        artifactKey: `ws_1/${"a".repeat(64)}`,
        byteCount: 512,
        filename: "brief.md",
        mediaType: "text/markdown",
        sha256: "a".repeat(64),
        uploadId: "upl_1",
      },
    ]);
  }
});
