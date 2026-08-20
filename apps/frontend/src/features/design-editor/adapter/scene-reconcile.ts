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
