import { z } from "zod";

/**
 * The durable transcript read — as-built contract item 8.
 *
 * "Message reads are body-free": the paginated listing carries role, sequence,
 * the content address, and the typed `refs[]`. `?include=bodies` hydrates that
 * page's bodies server-side in one round trip, and a body that cannot be served
 * comes back `null` **with a reason** rather than an empty string that would
 * render as a message nobody wrote. Both shapes are the same schema; absence is
 * explicit.
 */

/** The closed flavor vocabulary of `MessageRefFlavor` (REQ-21 / D0). */
export const MessageRefFlavorSchema = z.enum([
  "attachment",
  "context",
  "output",
  "open_gate",
  "next_action",
  "assumption",
  "workspace_output",
]);

export type MessageRefFlavor = z.infer<typeof MessageRefFlavorSchema>;

const MessageRefWireSchema = z.object({
  flavor: MessageRefFlavorSchema,
  workspace_id: z.string(),
  object_type: z.string(),
  object_id: z.string(),
  version: z.number().int().nullable().default(null),
  ordinal: z.number().int().min(0).default(0),
  label: z.string().nullable().default(null),
  kind: z.string().nullable().default(null),
  media_type: z.string().nullable().default(null),
  thumbnail_digest: z.string().nullable().default(null),
  /** Present on attachment refs: the chat upload whose bytes the chip can fetch. */
  upload_id: z.string().nullable().default(null),
});

export interface ChatMessageRef {
  flavor: MessageRefFlavor;
  workspaceId: string;
  objectType: string;
  objectId: string;
  version: number | null;
  ordinal: number;
  label: string | null;
  kind: string | null;
  mediaType: string | null;
  thumbnailDigest: string | null;
  uploadId: string | null;
}

export const ChatMessageRoleSchema = z.enum([
  "user",
  "assistant",
  "system",
  "tool",
]);

export type ChatMessageRole = z.infer<typeof ChatMessageRoleSchema>;

/** Why a hydrated body could not be served. Open set — branch on what you know. */
export const BodyUnavailableReasonSchema = z.string();

export const ChatMessageWireSchema = z.object({
  id: z.string().min(1),
  turn_id: z.string().min(1),
  thread_id: z.string().min(1),
  sequence: z.number().int(),
  role: ChatMessageRoleSchema,
  body_artifact_key: z.string(),
  body_sha256: z.string(),
  body: z.string().nullable().default(null),
  body_unavailable_reason: BodyUnavailableReasonSchema.nullable().default(null),
  created_at: z.string(),
  refs: z.array(MessageRefWireSchema).default([]),
});

export interface ChatMessage {
  id: string;
  turnId: string;
  threadId: string;
  sequence: number;
  role: ChatMessageRole;
  bodyArtifactKey: string;
  bodySha256: string;
  /** `null` on the body-free listing *and* on a body that could not be served. */
  body: string | null;
  /** Non-null only in the second case, so the two stay distinguishable. */
  bodyUnavailableReason: string | null;
  createdAt: string;
  refs: readonly ChatMessageRef[];
}

export function toChatMessage(
  wire: z.infer<typeof ChatMessageWireSchema>,
): ChatMessage {
  return {
    id: wire.id,
    turnId: wire.turn_id,
    threadId: wire.thread_id,
    sequence: wire.sequence,
    role: wire.role,
    bodyArtifactKey: wire.body_artifact_key,
    bodySha256: wire.body_sha256,
    body: wire.body,
    bodyUnavailableReason: wire.body_unavailable_reason,
    createdAt: wire.created_at,
    refs: wire.refs.map((ref) => ({
      flavor: ref.flavor,
      workspaceId: ref.workspace_id,
      objectType: ref.object_type,
      objectId: ref.object_id,
      version: ref.version,
      ordinal: ref.ordinal,
      label: ref.label,
      kind: ref.kind,
      mediaType: ref.media_type,
      thumbnailDigest: ref.thumbnail_digest,
      uploadId: ref.upload_id,
    })),
  };
}

export const ChatMessageListResponseSchema = z
  .object({
    data: z.array(ChatMessageWireSchema).default([]),
    meta: z
      .object({ next_cursor: z.string().nullable().default(null) })
      .default({ next_cursor: null }),
  })
  .transform((wire) => ({
    messages: wire.data.map(toChatMessage),
    nextCursor: wire.meta.next_cursor,
  }));

export type ChatMessagePage = z.infer<typeof ChatMessageListResponseSchema>;

export function unavailableMessageBody(reason: string): string {
  if (reason === "artifact_missing") {
    return "This earlier message could not be recovered. Please resend it in a new chat.";
  }
  return `This message's text is unavailable (${reason}).`;
}

/** The gate ids an assistant message is waiting on, in durable order. */
export function openGateIds(message: ChatMessage): readonly string[] {
  return message.refs
    .filter((ref) => ref.flavor === "open_gate")
    .slice()
    .sort((left, right) => left.ordinal - right.ordinal)
    .map((ref) => ref.objectId);
}
