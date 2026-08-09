import { z } from "zod";

/**
 * The durable thread shell (REQ-21), as the as-built contract serves it.
 *
 * Authority: the "As-built thread-shell contract" section at the end of
 * `docs/api-contracts/projects.md` (founder-ratified 2026-08-08), which
 * overrides the proposal above it. The four shapes that differ from the
 * proposal and are encoded here:
 *
 * 1. rename/pin and archive are **per thread**, not per project;
 * 2. list endpoints are cursor-paginated (`meta.next_cursor`), not `total`;
 * 3. `title` is nullable — an unnamed thread has no name until it earns one;
 * 4. create returns a superset (`pinned`, `project_id`, timestamps).
 */

/**
 * The pinned thread-status precedence vocabulary.
 *
 * Ordered most- to least-authoritative, and that order is the contract:
 * `archived > approval > needs-input > running > idle`. It is produced
 * server-side by `chat/schemas.py::thread_status` and re-derived here only for
 * optimistic local updates, so the two can be compared rather than guessed at.
 *
 * Note what is absent: the frontend proposal's `review`. No backend surface
 * emits it, so accepting it would leave a value nothing can ever produce.
 */
export const ThreadStatusSchema = z.enum([
  "archived",
  "approval",
  "needs-input",
  "running",
  "idle",
]);

export type ThreadStatus = z.infer<typeof ThreadStatusSchema>;

/** Most- to least-authoritative. Index 0 wins. */
export const THREAD_STATUS_PRECEDENCE: readonly ThreadStatus[] = [
  "archived",
  "approval",
  "needs-input",
  "running",
  "idle",
];

/**
 * Re-derive the status the server would compute.
 *
 * The rule that matters is the last one: an open gate outranks `running`,
 * because a gate is something the *user* must do and a badge that says
 * "running" while the conversation is blocked on them is the one wrong answer.
 */
export function deriveThreadStatus({
  archived,
  openGateKinds = [],
  running = false,
}: {
  archived: boolean;
  openGateKinds?: readonly string[];
  running?: boolean;
}): ThreadStatus {
  if (archived) return "archived";
  if (openGateKinds.includes("directive_confirmation")) return "approval";
  if (openGateKinds.length > 0) return "needs-input";
  if (running) return "running";
  return "idle";
}

/** The more urgent of two statuses, by the pinned precedence. */
export function mostUrgentThreadStatus(
  left: ThreadStatus,
  right: ThreadStatus,
): ThreadStatus {
  return THREAD_STATUS_PRECEDENCE.indexOf(left) <=
    THREAD_STATUS_PRECEDENCE.indexOf(right)
    ? left
    : right;
}

const ThreadWireSchema = z.object({
  id: z.string().min(1),
  title: z.string().nullable().default(null),
  href: z.string(),
  status: ThreadStatusSchema,
  pinned: z.boolean().default(false),
  project_id: z.string().min(1),
  created_at: z.string(),
  updated_at: z.string(),
});

export interface ChatThread {
  id: string;
  /** `null` for an unnamed thread. Render a placeholder; never render the id. */
  title: string | null;
  href: string;
  status: ThreadStatus;
  pinned: boolean;
  projectId: string;
  createdAt: string;
  updatedAt: string;
}

function toThread(wire: z.infer<typeof ThreadWireSchema>): ChatThread {
  return {
    id: wire.id,
    title: wire.title,
    href: wire.href,
    status: wire.status,
    pinned: wire.pinned,
    projectId: wire.project_id,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

export const ChatThreadSchema = ThreadWireSchema.transform(toThread);

export const ChatThreadResponseSchema = z
  .object({ data: ThreadWireSchema })
  .transform((wire) => toThread(wire.data));

export const ChatThreadListResponseSchema = z
  .object({
    data: z.array(ThreadWireSchema).default([]),
    meta: z
      .object({ next_cursor: z.string().nullable().default(null) })
      .default({ next_cursor: null }),
  })
  .transform((wire) => ({
    threads: wire.data.map(toThread),
    nextCursor: wire.meta.next_cursor,
  }));

export type ChatThreadPage = z.infer<typeof ChatThreadListResponseSchema>;

/** The thread title a surface shows when the thread has not earned one. */
export const UNTITLED_THREAD_LABEL = "New chat";

export function threadLabel(thread: ChatThread): string {
  return thread.title ?? UNTITLED_THREAD_LABEL;
}
