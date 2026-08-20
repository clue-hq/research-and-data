import type { ReconcileEvent } from "../engine/scene/editQueue";

/**
 * AD3.2: the scene lane's reconcile → user-facing message table.
 *
 * The edit queue (`engine/scene/editQueue.ts`, verbatim extracted upstream
 * code) reports three things through one callback: a drain-time `divergence`,
 * a server `rejected` batch, and a `request_failed` transport error. The D10
 * posture (ratified 2026-08-20, mapping contract §4) is the website lane's:
 * a concurrent writer is a quiet reload with ONE informational note, and only a
 * genuinely invalid batch earns an inline error.
 *
 * Pure on purpose: the controller owns the reload and the queue resync; this
 * decides only what the inspector's two existing lines say
 * (`chat-shell.module.css` `.inspectorStatusNote` / `.inspectorStatusError`).
 *
 * AD3.3 adds the second reader of an upstream prose format — the history step's
 * (`historyFailureToMessages` at the foot of this file). It lives HERE, beside
 * the queue's, because the containment is the point: every place this lane has
 * to read a status back out of an extracted module's sentence is in one file,
 * with one test pinning the upstream templates against the real sources.
 */

export interface SceneReconcileMessages {
  note: string | null;
  error: string | null;
}

/** The website lane's ratified string, copied verbatim from
 * `hooks/use-web-manual-edits.ts:158` — the two lanes say the same sentence
 * about the same event, so it is lifted, never re-worded. */
export const SCENE_RELOADED_NOTE = "Document moved on — reloaded.";

/** Likewise `use-web-manual-edits.ts:163` (and `webDocuments.ts`'s own 422
 * fallback): what an unreadable rejection says instead of an internal string. */
export const SCENE_WRITE_FALLBACK_ERROR = "This edit could not be applied.";

/**
 * The fixed head of the upstream rejection diagnostic
 * (`editQueue.ts:142`):
 *
 *     `The server rejected a persisted edit batch (${response.status}): ${JSON.stringify(detail)}`
 *
 * Exported so `scene-reconcile.test.ts` can pin it against that file.
 */
export const REJECTED_BATCH_PREFIX = "The server rejected a persisted edit batch (";

/**
 * A PARSE OF AN UPSTREAM FORMAT, deliberately contained here.
 *
 * `editQueue.ts` flattens the HTTP status and the response body into one prose
 * sentence before anyone downstream sees them, and it is read-only extracted
 * code — so recovering "was this a 409 or a 422?" means reading that sentence
 * back. Everything fragile about that lives in this one function, and
 * `scene-reconcile.test.ts` pins the exact upstream template so a reword fails
 * the suite instead of quietly degrading every rejection to the reload note.
 */
const REJECTED_BATCH_PATTERN =
  /^The server rejected a persisted edit batch \((\d+)\): ([\s\S]*)$/;

/** The FastAPI error shapes the design API's `/documents/{id}/operations`
 * actually returns: `{detail: {code, message, diagnostics?}}` (both the 409
 * base-version mismatch and every 422), or a bare string `detail`. */
function serverCode(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  if (!detail || typeof detail !== "object") {
    return null;
  }
  const code = (detail as { code?: unknown }).code;
  return typeof code === "string" && code ? code : null;
}

function firstServerMessage(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") {
    return detail.trim() ? detail : null;
  }
  if (!detail || typeof detail !== "object") {
    return null;
  }
  const record = detail as { diagnostics?: unknown; message?: unknown };
  const first = Array.isArray(record.diagnostics) ? record.diagnostics[0] : null;
  const diagnosticMessage = (first as { message?: unknown } | null)?.message;
  if (typeof diagnosticMessage === "string" && diagnosticMessage.trim()) {
    return diagnosticMessage;
  }
  return typeof record.message === "string" && record.message.trim()
    ? record.message
    : null;
}

const RELOADED: SceneReconcileMessages = {
  note: SCENE_RELOADED_NOTE,
  error: null,
};

export function reconcileToMessages(
  event: ReconcileEvent,
): SceneReconcileMessages {
  // A divergence and a failed request are both "the local scene is no longer
  // the truth" — the D10 note, and the caller reloads. The divergence
  // diagnostic's own text ("report it as an engine bug") is for the console,
  // not for a marketer editing an ad.
  if (event.kind !== "rejected") {
    return RELOADED;
  }
  const parsed = REJECTED_BATCH_PATTERN.exec(event.diagnostic.message);
  if (!parsed) {
    // Unrecognised (an upstream reword): reload rather than print an internal
    // diagnostic at the user. The safe direction, and the pinned test above is
    // what stops it becoming the silent normal.
    return RELOADED;
  }
  // 409 IS the concurrent-writer case — `require_base_version`'s
  // `edits.base_version_mismatch`. Same event, same sentence as a divergence.
  if (parsed[1] === "409") {
    return RELOADED;
  }
  // Everything else (notably 422, an invalid batch) is about THIS edit, so the
  // server's own words are the useful thing to show.
  let body: unknown = null;
  try {
    body = JSON.parse(parsed[2]);
  } catch {
    // The queue's own `response.json().catch(() => ({}))` already tolerates a
    // non-JSON body; a truncated one lands here. Either way: the fallback.
  }
  return {
    note: null,
    error: firstServerMessage(body) ?? SCENE_WRITE_FALLBACK_ERROR,
  };
}

/* ────────────────────────────────────────────────────────────────────────────
 * AD3.3 — the history step's failure, read back out of its own upstream prose.
 * ─────────────────────────────────────────────────────────────────────────── */

/**
 * The fixed head of the upstream history-step error
 * (`engine/scene/structuredEdits.ts:275`):
 *
 *     `${action} failed (${response.status}): ${JSON.stringify(detail)}`
 *
 * Exported so `scene-reconcile.test.ts` can pin it against that file.
 */
export const HISTORY_STEP_FAILURE_PATTERN =
  /^(?:undo|redo) failed \((\d+)\): ([\s\S]*)$/;

/** The two `POST /documents/{id}/{undo,redo}` refusals that mean only "the
 * stack raced empty" (`lumen_api/main.py` — `perform_undo_step` /
 * `redo_document`). Everything else the server names is about THIS step. */
const EMPTY_STACK_CODES = new Set([
  "history.nothing_to_undo",
  "history.nothing_to_redo",
]);

export interface SceneHistoryFailure {
  /** The step could not run because there was nothing left to undo/redo. The
   * controller resyncs quietly: nothing changed, and nothing needs saying. */
  emptyStack: boolean;
  /** What to show on the inspector's inline error line; null iff
   * `emptyStack`. */
  error: string | null;
}

const EMPTY_STACK: SceneHistoryFailure = { emptyStack: true, error: null };

/**
 * A SECOND PARSE OF AN UPSTREAM FORMAT, deliberately contained beside the
 * first.
 *
 * `structuredEdits.ts`'s `undoDocument`/`redoDocument` throw a plain `Error`
 * whose message flattens the HTTP status and the response body into prose
 * (`structuredEdits.ts:273-276`), and it is read-only extracted code — so
 * recovering "was this the empty stack, or a real refusal?" means reading that
 * sentence back. The test pins the exact upstream template, so a reword fails
 * the suite instead of quietly turning every failure into a silent reload.
 *
 * The rule, in one sentence: **a 409 is quiet unless the server named a reason
 * that is not an empty stack.** An unreadable 409 therefore stays quiet (the
 * website lane's precedent, `use-web-manual-edits.ts:191-193`, which resyncs on
 * the status alone), while `history.not_invertible` — a 409 that means the step
 * genuinely cannot run — says so in the server's own words rather than
 * reloading and looking like a button that did nothing.
 */
export function historyFailureToMessages(cause: unknown): SceneHistoryFailure {
  const message = cause instanceof Error ? cause.message : "";
  const parsed = HISTORY_STEP_FAILURE_PATTERN.exec(message);
  if (!parsed) {
    // Not a server refusal at all: a transport failure, or an upstream reword.
    // Either way the raw string is internal prose, never shown to the user.
    return { emptyStack: false, error: SCENE_WRITE_FALLBACK_ERROR };
  }
  let body: unknown = null;
  try {
    body = JSON.parse(parsed[2]);
  } catch {
    // Upstream's own `response.json().catch(() => ({}))` yields `{}`; a
    // truncated body lands here.
  }
  const code = serverCode(body);
  if (parsed[1] === "409" && (code === null || EMPTY_STACK_CODES.has(code))) {
    return EMPTY_STACK;
  }
  return {
    emptyStack: false,
    error: firstServerMessage(body) ?? SCENE_WRITE_FALLBACK_ERROR,
  };
}
