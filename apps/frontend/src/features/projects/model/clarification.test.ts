import assert from "node:assert/strict";
import test from "node:test";
import {
  composeClarificationReply,
  openClarification,
  type ClarificationAnswer,
} from "./clarification";
import type { ChatClarificationPart } from "./chat-parts";
import type { TranscriptMessage } from "./chat-transcript";

function clarificationPart(
  overrides: Partial<ChatClarificationPart> = {},
): ChatClarificationPart {
  return {
    kind: "clarification",
    partId: "clarification:doc-1",
    revision: 1,
    documentId: "doc-1",
    documentTitle: "Acme retargeting ad",
    docKind: "scene",
    accountName: "Acme",
    runId: "run-1",
    questions: [
      {
        id: "q1",
        question: "Which offer should lead?",
        whyItMatters: "It sets the headline.",
        options: ["Free trial", "Demo"],
        default: "Free trial",
        allowFreeform: true,
      },
    ],
    ...overrides,
  };
}

function message(overrides: Partial<TranscriptMessage> = {}): TranscriptMessage {
  return {
    id: "m1",
    turnId: "turn-1",
    role: "assistant",
    createdAt: null,
    body: null,
    bodyUnavailableReason: null,
    parts: [],
    refs: [],
    live: false,
    state: "completed",
    failureCode: null,
    optimistic: false,
    legNotices: [],
    generatingDesign: false,
    ...overrides,
  };
}

test("the latest settled asking turn is the open one, with its parts in order", () => {
  const first = clarificationPart({ partId: "clarification:a", documentId: "a" });
  const second = clarificationPart({ partId: "clarification:b", documentId: "b" });
  const transcript = [
    message({ id: "m0", turnId: "turn-0", role: "user" }),
    message({
      id: "m1",
      turnId: "turn-1",
      parts: [first, second],
      state: "awaiting_input",
    }),
  ];

  const open = openClarification(transcript);
  assert.ok(open);
  assert.equal(open.turnId, "turn-1");
  assert.deepEqual(
    open.parts.map((part) => part.documentId),
    ["a", "b"],
  );
});

test("a later message closes the card", () => {
  const transcript = [
    message({ id: "m1", turnId: "turn-1", parts: [clarificationPart()] }),
    message({ id: "m2", turnId: "turn-2", role: "user" }),
  ];
  assert.equal(openClarification(transcript), null);
});

test("a turn still running is never open", () => {
  const transcript = [
    message({
      id: "m1",
      turnId: "turn-1",
      parts: [clarificationPart()],
      state: "running",
      live: true,
    }),
  ];
  assert.equal(openClarification(transcript), null);
});

test("a settled turn without clarification parts is not open", () => {
  const transcript = [message({ id: "m1", turnId: "turn-1", parts: [] })];
  assert.equal(openClarification(transcript), null);
  assert.equal(openClarification([]), null);
});

test("one document renders every answer kind in the plan's exact format", () => {
  const part = clarificationPart({
    questions: [
      {
        id: "q1",
        question: "Which offer should lead?",
        whyItMatters: "",
        options: ["Free trial", "Demo"],
        default: "Free trial",
        allowFreeform: true,
      },
      {
        id: "q2",
        question: "What tone?",
        whyItMatters: "",
        options: ["Bold"],
        default: "Bold",
        allowFreeform: true,
      },
      {
        id: "q3",
        question: "Which logo lockup?",
        whyItMatters: "",
        options: [],
        default: "Horizontal",
        allowFreeform: true,
      },
    ],
  });
  const answers = new Map<string, ClarificationAnswer>([
    ["q1", { kind: "option", value: "Demo" }],
    ["q2", { kind: "freeform", value: "dry and technical" }],
    ["q3", { kind: "skipped", default: "Horizontal" }],
  ]);

  const { text, contextRefs } = composeClarificationReply([{ part, answers }]);
  assert.equal(
    text,
    [
      'For "Acme retargeting ad":',
      "- Which offer should lead? — Demo",
      "- What tone? — something else: dry and technical",
      "- Which logo lockup? — use your default (Horizontal)",
    ].join("\n"),
  );
  assert.deepEqual(contextRefs, [
    { objectId: "doc-1", objectType: "design_document", version: null },
  ]);
});

test("two documents are separated by a blank line and carry two refs in order", () => {
  const first = clarificationPart();
  const second = clarificationPart({
    partId: "clarification:doc-2",
    documentId: "doc-2",
    documentTitle: "Globex launch ad",
    questions: [
      {
        id: "q9",
        question: "Which product shot?",
        whyItMatters: "",
        options: [],
        default: "Hero",
        allowFreeform: true,
      },
    ],
  });

  const { text, contextRefs } = composeClarificationReply([
    {
      part: first,
      answers: new Map<string, ClarificationAnswer>([
        ["q1", { kind: "option", value: "Demo" }],
      ]),
    },
    {
      part: second,
      answers: new Map<string, ClarificationAnswer>([
        ["q9", { kind: "skipped", default: "Hero" }],
      ]),
    },
  ]);

  assert.equal(
    text,
    [
      'For "Acme retargeting ad":',
      "- Which offer should lead? — Demo",
      "",
      'For "Globex launch ad":',
      "- Which product shot? — use your default (Hero)",
    ].join("\n"),
  );
  assert.deepEqual(contextRefs, [
    { objectId: "doc-1", objectType: "design_document", version: null },
    { objectId: "doc-2", objectType: "design_document", version: null },
  ]);
});

test("a document with no answers contributes neither a block nor a ref", () => {
  const { text, contextRefs } = composeClarificationReply([
    { part: clarificationPart(), answers: new Map<string, ClarificationAnswer>() },
  ]);
  assert.equal(text, "");
  assert.deepEqual(contextRefs, []);
});
