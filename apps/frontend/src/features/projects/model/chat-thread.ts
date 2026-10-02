import { z } from "zod";
import { projectChatHref } from "@/features/chat-shell/model/chat-shell-routes";
import type { ThreadDesignLegWire } from "@/features/chat-shell/model/agent-run-lock";

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

/**
 * The speaker projection (`chat/schemas.py::ThreadSpeakerWire`, P3.4 / PD-part3
 * §1-D1): who owns the thread right now, and — the part the editor lock needs —
 * the DURABLE state of its design leg.
 *
 * Parsed by hand rather than inline in the wire schema, for one reason: it must
 * be impossible for this optional, secondary field to take the whole thread list
 * down. Anything unreadable resolves to `null`, which the lock reads as UNKNOWN
 * (never as "there is no leg" — that is the dangerous direction; see
 * `agent-run-lock.DesignLegFact`).
 */
const ThreadSpeakerWireSchema = z.object({
  // Not consumed, but load-bearing: it is what makes a malformed or foreign
  // object fail this parse instead of defaulting its way into a false answer.
  role: z.string(),
  design_leg_id: z.string().nullable().default(null),
  // Deliberately a plain string, not the platform's `Literal` pair: a state
  // this build has not been taught still proves a leg EXISTS, and refusing the
  // whole speaker over it would report "no leg" for a thread that has one.
  design_leg_state: z.string().nullable().default(null),
});

function toThreadDesignLeg(raw: unknown): ThreadDesignLegWire | null {
  const parsed = ThreadSpeakerWireSchema.safeParse(raw);
  if (!parsed.success) return null;
  const state = parsed.data.design_leg_state;
  return {
    legId: parsed.data.design_leg_id,
    state:
      state === null
        ? null
        : state === "open_awaiting_user"
          ? "open_awaiting_user"
          : // Fail-safe: `running`, or anything this build cannot name. Both
            // mean a leg is present and not parked on the user, which is the
            // reading that holds the editor shut rather than opening it.
            "running",
  };
}

/**
 * The discovery run a thread is holding (`chat/schemas.py::ThreadDiscoveryWire`).
 *
 * While it is present the thread is busy: the backend holds every message sent
 * to it until the run's wake turn ends. It is served only by the thread LIST
 * read; every other thread projection sends `null`.
 */
export const ThreadDiscoverySchema = z.object({
  run_id: z.string(),
  stoppable: z.boolean(),
});

export interface ThreadDiscovery {
  runId: string;
  /** `false` once the run has ended: Stop has nothing left to stop. */
  stoppable: boolean;
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
  // `unknown` on purpose: the shape is validated in `toThreadDesignLeg`, where
  // a failure degrades this one field instead of the read.
  speaker: z.unknown().optional(),
  discovery: ThreadDiscoverySchema.nullable().optional(),
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
  /**
   * The thread's design leg as the DURABLE read reports it, or `null` when this
   * read did not derive one (the platform sends `speaker: null` on the
   * tool-reference projections; absent knowledge is never a guess).
   *
   * This is the editor lock's cold-load answer: the turn-stream backlog replays
   * only the last few turns, so a leg opened before that is invisible to the
   * frames and this is the only thing that knows about it.
   */
  designLeg: ThreadDesignLegWire | null;
  /** The discovery run holding this thread busy, or `null` when none is. */
  discovery: ThreadDiscovery | null;
}

export type ProjectThreadRouteResolution =
  | { kind: "selected"; thread: ChatThread; canonicalize: boolean }
  | { kind: "not-found"; requestedThreadId: string }
  | { kind: "empty" };

/** Resolve a URL thread only from this project's tenant-scoped thread page. */
export function resolveProjectThreadRoute(
  threads: readonly ChatThread[],
  requestedThreadId: string | null,
): ProjectThreadRouteResolution {
  if (requestedThreadId) {
    const requested = threads.find((thread) => thread.id === requestedThreadId);
    if (requested) {
      return { kind: "selected", thread: requested, canonicalize: false };
    }
  }
  const fallback =
    threads.find((thread) => thread.status !== "archived") ?? threads[0];
  if (fallback) {
    return {
      kind: "selected",
      thread: fallback,
      canonicalize: fallback.id !== requestedThreadId,
    };
  }
  return requestedThreadId
    ? { kind: "not-found", requestedThreadId }
    : { kind: "empty" };
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
    designLeg: toThreadDesignLeg(wire.speaker),
    discovery: wire.discovery
      ? { runId: wire.discovery.run_id, stoppable: wire.discovery.stoppable }
      : null,
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

/**
 * The canonical path-based href for a thread (Phase R, rulings R1/R2).
 *
 * Single source of thread-URL truth for the controller's writers: builds
 * `/projects/{id}/chats/{threadId}` through the ratified route helper,
 * carrying the current query along minus the legacy `thread` key — which is
 * never written again (`docs/superpowers/plans/2026-08-17-phase-r-chat-route-migration.md`).
 */
export function threadRouteHref(
  projectId: string,
  threadId: string,
  currentQuery: string,
): string {
  const query = new URLSearchParams(currentQuery);
  query.delete("thread");
  return projectChatHref(projectId, threadId, Object.fromEntries(query));
}
