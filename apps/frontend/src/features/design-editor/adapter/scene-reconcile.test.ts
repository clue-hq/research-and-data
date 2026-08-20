import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { it } from "node:test";
import type { Diagnostic } from "../engine/scene/contracts";
import type { ReconcileEvent } from "../engine/scene/editQueue";
import {
  REJECTED_BATCH_PREFIX,
  SCENE_RELOADED_NOTE,
  SCENE_WRITE_FALLBACK_ERROR,
  reconcileToMessages,
} from "./scene-reconcile";

/**
 * AD3.2: the reconcile→message table, and the pin that keeps it honest.
 *
 * The queue is read-only extracted code and it FLATTENS the HTTP status into
 * prose (`editQueue.ts:142`), so the only way to tell a concurrent-writer 409
 * from an invalid-batch 422 is to parse that prose. The parse is contained in
 * `scene-reconcile.ts`; this file pins the exact upstream template against the
 * real source file, so an upstream reword fails here loudly instead of quietly
 * degrading every rejection to the reload note.
 */

const REJECTED_DIAGNOSTIC_TEMPLATE =
  "`The server rejected a persisted edit batch (${response.status}): ${JSON.stringify(detail)}`";

const UPSTREAM_QUEUE = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../engine/scene/editQueue.ts",
  ),
  "utf8",
);

/** The message the queue actually builds, assembled here the way it assembles
 * it — so a fixture can never drift from the code it stands in for. */
function rejectedMessage(status: number, detail: unknown): string {
  return `The server rejected a persisted edit batch (${status}): ${JSON.stringify(detail)}`;
}

function event(
  kind: ReconcileEvent["kind"],
  message: string,
  overrides: Partial<Diagnostic> = {},
): ReconcileEvent {
  return {
    kind,
    serverScene: null,
    serverVersion: null,
    diagnostic: {
      severity: "error",
      phase: "operation",
      code: "EDITOR_WASM_EDIT_REJECTED",
      message,
      subject: { kind: "document" },
      hint: null,
      ...overrides,
    },
  };
}

it("pins the upstream rejection template the parse depends on", () => {
  // The literal, verbatim from `editQueue.ts:142`. If upstream rewords it, the
  // parse silently stops recognising a 422 — so this assertion is the alarm.
  assert.ok(
    UPSTREAM_QUEUE.includes(REJECTED_DIAGNOSTIC_TEMPLATE),
    "editQueue.ts no longer formats its rejection diagnostic as `scene-reconcile.ts` parses it",
  );
  // …and the constant the parse anchors on is that template's fixed head.
  assert.ok(REJECTED_DIAGNOSTIC_TEMPLATE.includes(REJECTED_BATCH_PREFIX));
});

it("reads a drain-time divergence as the D10 reload note", () => {
  assert.deepEqual(
    reconcileToMessages(
      event(
        "divergence",
        "Optimistic scene diverged from the server after reconciliation.",
      ),
    ),
    { note: SCENE_RELOADED_NOTE, error: null },
  );
});

it("reads a failed request as the same reload note, never a raw transport string", () => {
  assert.deepEqual(
    reconcileToMessages(
      event("request_failed", "Persisting edits to the server failed: offline"),
    ),
    { note: SCENE_RELOADED_NOTE, error: null },
  );
});

it("reads a 409 rejection as the concurrent-writer note (the D10 case)", () => {
  const detail = {
    detail: {
      code: "edits.base_version_mismatch",
      message:
        "base_version 4 does not match current document version 5; reload the document and rebuild the edit",
      current_version: 5,
    },
  };
  assert.deepEqual(reconcileToMessages(event("rejected", rejectedMessage(409, detail))), {
    note: SCENE_RELOADED_NOTE,
    error: null,
  });
});

it("surfaces the server's own first diagnostic for a 422 invalid batch", () => {
  const detail = {
    detail: {
      code: "LUMV0100",
      message: "the batch is invalid",
      diagnostics: [
        { severity: "error", code: "LUMV0100", message: "a scene needs at least one page" },
        { severity: "error", code: "LUMV0101", message: "a second complaint" },
      ],
    },
  };
  assert.deepEqual(reconcileToMessages(event("rejected", rejectedMessage(422, detail))), {
    note: null,
    error: "a scene needs at least one page",
  });
});

it("falls back to the detail's own message when it carries no diagnostics", () => {
  const detail = {
    detail: { code: "operations.empty", message: "operations cannot be empty" },
  };
  assert.deepEqual(reconcileToMessages(event("rejected", rejectedMessage(422, detail))), {
    note: null,
    error: "operations cannot be empty",
  });
});

it("accepts a bare string detail (FastAPI's other shape)", () => {
  assert.deepEqual(
    reconcileToMessages(event("rejected", rejectedMessage(422, { detail: "Not Found" }))),
    { note: null, error: "Not Found" },
  );
});

it("shows the plain fallback for a 422 whose detail cannot be read", () => {
  // The queue's own `.catch(() => ({}))` produces exactly this when the body is
  // not JSON; a truncated/garbled body is the other shape.
  assert.deepEqual(reconcileToMessages(event("rejected", rejectedMessage(422, {}))), {
    note: null,
    error: SCENE_WRITE_FALLBACK_ERROR,
  });
  const garbled = `${REJECTED_BATCH_PREFIX}422): {"detail":`;
  assert.deepEqual(reconcileToMessages(event("rejected", garbled)), {
    note: null,
    error: SCENE_WRITE_FALLBACK_ERROR,
  });
});

it("surfaces the server's own words for any other status, not the queue's prose", () => {
  assert.deepEqual(
    reconcileToMessages(
      event("rejected", rejectedMessage(500, { detail: "Internal Server Error" })),
    ),
    { note: null, error: "Internal Server Error" },
  );
});

it("treats a rejection it cannot parse at all as the reload note", () => {
  // Safe direction: reload rather than show the user an unparsed internal
  // diagnostic. This is the branch the upstream-template pin above protects.
  assert.deepEqual(
    reconcileToMessages(event("rejected", "something upstream reworded")),
    { note: SCENE_RELOADED_NOTE, error: null },
  );
});
