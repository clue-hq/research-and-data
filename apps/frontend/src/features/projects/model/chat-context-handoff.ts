import { z } from "zod";
import { ProjectEntitySchema, ProjectEntityTypeSchema } from "./project-workspace";

export const CHAT_CONTEXT_HANDOFF_TTL_MS = 30 * 60 * 1_000;
const CHAT_CONTEXT_HANDOFF_SCHEMA_VERSION = 1;
const CHAT_CONTEXT_HANDOFF_PREFIX = "clue:chat-context-handoff:";

export const ChatContextRefSchema = z.object({
  objectId: z.string().min(1).max(200),
  objectType: ProjectEntityTypeSchema,
  version: z.number().int().positive().nullable().default(null),
}).strict();

export const PreparedComposerContextSchema = z.object({
  projectId: z.string().min(1),
  threadId: z.string().min(1).nullable(),
  entities: z.array(ProjectEntitySchema).min(1).max(100),
});

export const ChatContextHandoffSchema = z.object({
  schemaVersion: z.literal(CHAT_CONTEXT_HANDOFF_SCHEMA_VERSION),
  handoffId: z.string().uuid(),
  createdAt: z.number().int().nonnegative(),
  expiresAt: z.number().int().positive(),
  source: z.enum(["accounts", "contacts"]),
  projectId: z.string().min(1),
  threadId: z.string().min(1),
  entities: z.array(ProjectEntitySchema).min(1).max(100),
}).strict();

export type ChatContextRef = z.infer<typeof ChatContextRefSchema>;
export type ChatContextHandoff = z.infer<typeof ChatContextHandoffSchema>;
export type PreparedComposerContext = z.infer<
  typeof PreparedComposerContextSchema
>;

/**
 * Later entries win by id, order kept. Two callers: the composer's catalog
 * merged with its selection, and — the same rule — a selection merged with
 * entities the server just prepared for an in-chat "Add to chat" (a prepared
 * entity replaces a same-id selection, carrying the version just pinned).
 */
export function mergeComposerContextEntities(
  catalog: readonly z.infer<typeof ProjectEntitySchema>[],
  selected: readonly z.infer<typeof ProjectEntitySchema>[],
) {
  const merged = new Map(catalog.map((entity) => [entity.id, entity]));
  for (const entity of selected) merged.set(entity.id, entity);
  return [...merged.values()];
}

export function remainingComposerContextEntities(
  current: readonly z.infer<typeof ProjectEntitySchema>[],
  submittedEntityIds: readonly string[],
) {
  const submitted = new Set(submittedEntityIds);
  return current.filter((entity) => !submitted.has(entity.id));
}

function keyFor(handoffId: string) {
  return `${CHAT_CONTEXT_HANDOFF_PREFIX}${handoffId}`;
}

export function createChatContextHandoff(input: {
  entities: ChatContextHandoff["entities"];
  handoffId?: string;
  now?: number;
  projectId: string;
  source: ChatContextHandoff["source"];
  threadId: string;
}): ChatContextHandoff {
  const now = input.now ?? Date.now();
  return ChatContextHandoffSchema.parse({
    schemaVersion: CHAT_CONTEXT_HANDOFF_SCHEMA_VERSION,
    handoffId: input.handoffId ?? crypto.randomUUID(),
    createdAt: now,
    expiresAt: now + CHAT_CONTEXT_HANDOFF_TTL_MS,
    source: input.source,
    projectId: input.projectId,
    threadId: input.threadId,
    entities: input.entities,
  });
}

export function writeChatContextHandoff(
  storage: Pick<Storage, "getItem" | "setItem">,
  handoff: ChatContextHandoff,
) {
  const validated = ChatContextHandoffSchema.parse(handoff);
  storage.setItem(keyFor(validated.handoffId), JSON.stringify(validated));
  const replay = storage.getItem(keyFor(validated.handoffId));
  if (!replay || !ChatContextHandoffSchema.safeParse(JSON.parse(replay)).success) {
    throw new Error("the chat draft handoff could not be stored safely");
  }
}

export function readChatContextHandoff(
  storage: Pick<Storage, "getItem" | "removeItem">,
  handoffId: string,
  options: { now?: number; projectId: string; threadId?: string },
): ChatContextHandoff | null {
  const key = keyFor(handoffId);
  const raw = storage.getItem(key);
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    storage.removeItem(key);
    return null;
  }
  const result = ChatContextHandoffSchema.safeParse(parsed);
  const now = options.now ?? Date.now();
  if (
    !result.success ||
    result.data.expiresAt <= now ||
    result.data.projectId !== options.projectId ||
    (options.threadId !== undefined && result.data.threadId !== options.threadId)
  ) {
    storage.removeItem(key);
    return null;
  }
  return result.data;
}

export function updateChatContextHandoffEntities(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem">,
  handoffId: string,
  entities: ChatContextHandoff["entities"],
) {
  const raw = storage.getItem(keyFor(handoffId));
  if (!raw) return;
  let decoded: unknown;
  try {
    decoded = JSON.parse(raw);
  } catch {
    storage.removeItem(keyFor(handoffId));
    return;
  }
  const parsed = ChatContextHandoffSchema.safeParse(decoded);
  if (!parsed.success) {
    storage.removeItem(keyFor(handoffId));
    return;
  }
  if (!entities.length) {
    storage.removeItem(keyFor(handoffId));
    return;
  }
  writeChatContextHandoff(storage, { ...parsed.data, entities });
}

export function deleteChatContextHandoff(
  storage: Pick<Storage, "removeItem">,
  handoffId: string,
) {
  storage.removeItem(keyFor(handoffId));
}
