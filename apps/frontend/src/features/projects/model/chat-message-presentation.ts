import type { GateAnswerDisplay } from "./chat-gate";

/**
 * Customer-facing projection for durable transcript bodies.
 *
 * Raw bodies remain immutable and inspectable. Normal chat must not expose the
 * transport JSON, UUIDs, hashes, or tenant-scoped object ids they contain.
 */

const UUID_SOURCE =
  "[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const ICP_GATE_REFERENCE = new RegExp(
  `\\bICP gate\\s+\`?${UUID_SOURCE}\`?`,
  "gi",
);
const UUID = new RegExp(`\\b${UUID_SOURCE}\\b`, "gi");
const SHA256 = /\b[0-9a-f]{64}\b/gi;
const SCOPED_IDS: readonly [RegExp, string][] = [
  [/\bws_[a-z0-9_.:-]+\b/gi, "the current workspace"],
  [/\bprj_[a-z0-9_.:-]+\b/gi, "this project"],
  [/\bthr_[a-z0-9_.:-]+\b/gi, "this conversation"],
  [/\busr_[a-z0-9_.:-]+\b/gi, "the workspace member"],
];

/** Same-origin public byte route used only to present a durable design reference thumbnail. */
export function designReferenceThumbnailUrl(digest: string): string {
  return `/api/clue/design-public/asset-store/${digest}`;
}

/**
 * Same-origin, authenticated byte route for one chat upload.
 *
 * An attachment ref names a content-addressed artifact key, which no browser may
 * fetch directly; the upload id is the tenant-scoped handle the BFF will serve.
 */
export function chatUploadBytesUrl(uploadId: string): string {
  return `/api/clue/frontend/v1/uploads/${encodeURIComponent(uploadId)}/bytes`;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * Fallback only: durable gate reads provide the authoritative, kind-specific
 * display. This parser merely prevents a historical structured answer from
 * falling through as raw JSON when that read is unavailable.
 */
export function gateResponseBodyDisplay(
  body: string | null,
): GateAnswerDisplay | null {
  if (body === null || !body.trim().startsWith("{")) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return null;
  }
  const value = record(parsed);
  if (value?.kind !== "gate_response") return null;

  const decision = value.decision;
  const revisionRequest = value.revision_request;
  if (decision === "approved") return { detail: null, label: "Approved" };
  if (decision === "rejected") return { detail: null, label: "Declined" };
  if (decision === "revised") {
    return {
      detail:
        typeof revisionRequest === "string"
          ? revisionRequest.trim() || null
          : null,
      label: "Changes requested",
    };
  }
  return { detail: null, label: "Decision submitted" };
}

export function humanizeMessageBody(body: string): string {
  let display = body
    .replace(ICP_GATE_REFERENCE, "the saved profile proposal")
    .replace(SHA256, "secure verification")
    .replace(UUID, "the saved item");
  for (const [pattern, replacement] of SCOPED_IDS) {
    display = display.replace(pattern, replacement);
  }
  return display
    .replace(/\bworkspace_id\s*:\s*/gi, "Workspace: ")
    .replace(/\bgate_id\s*:\s*/gi, "Proposal: ")
    .replace(/\bexpected_subject_sha256\s*:\s*/gi, "");
}

/**
 * A chip label that stays one line: names over `max` characters keep their
 * head and their extension around an ellipsis (`long_name…txt`), so a file is
 * still recognisable without the chip growing past the message. The full
 * name stays on the chip's `title`.
 */
export function truncateAttachmentLabel(label: string, max = 60): string {
  if (label.length <= max) return label;
  const dot = label.lastIndexOf(".");
  const ext = dot > 0 && label.length - dot <= 10 ? label.slice(dot + 1) : "";
  const head = label.slice(0, Math.max(1, max - ext.length - 1));
  return `${head}…${ext}`;
}
