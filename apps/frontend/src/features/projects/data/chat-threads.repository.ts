import {
  ChatThreadListResponseSchema,
  ChatThreadResponseSchema,
  deriveThreadStatus,
  type ChatThread,
  type ChatThreadPage,
} from "../model/chat-thread";
import { chatRequest, type ChatTransport } from "./chat-api";
import { fixtureThreads } from "./chat.fixture";

/**
 * Thread CRUD over the as-built contract.
 *
 * Every mutation is per-thread and cursor-paginated, per the founder-ratified
 * as-built section: `PATCH …/threads/:threadId` for rename/pin,
 * `POST …/threads/:threadId/archive` for a reversible status flip, and
 * `GET …/threads` for the first-class paginated list. Project rename is owned by the project workspace repository; bulk archive
 * is not implemented by the backend and is not offered here.
 */
export interface ChatThreadsRepository {
  list(input: {
    projectId: string;
    status?: "active" | "archived";
    limit?: number;
    cursor?: string;
  }): Promise<ChatThreadPage>;
  create(input: {
    idempotencyKey?: string;
    projectId: string;
    title?: string | null;
  }): Promise<ChatThread>;
  update(input: {
    projectId: string;
    threadId: string;
    title?: string;
    pinned?: boolean;
  }): Promise<ChatThread>;
  archive(input: { projectId: string; threadId: string }): Promise<ChatThread>;
}

function threadPath(projectId: string, suffix = ""): string {
  return `/projects/${encodeURIComponent(projectId)}/threads${suffix}`;
}

export function createHttpChatThreadsRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ChatThreadsRepository {
  return {
    async list({ projectId, status, limit, cursor }) {
      return ChatThreadListResponseSchema.parse(
        await chatRequest(transport, threadPath(projectId), {
          query: { status, limit, cursor },
        }),
      );
    },
    async create({ idempotencyKey, projectId, title }) {
      return ChatThreadResponseSchema.parse(
        await chatRequest(transport, threadPath(projectId), {
          method: "POST",
          idempotencyKey,
          // `title` is optional on create (as-built item 7): an unnamed thread
          // is `title: null`, and a blank string is refused by the backend.
          body: { title: title?.trim() ? title.trim() : null },
        }),
      );
    },
    async update({ projectId, threadId, title, pinned }) {
      return ChatThreadResponseSchema.parse(
        await chatRequest(
          transport,
          `${threadPath(projectId)}/${encodeURIComponent(threadId)}`,
          {
            method: "PATCH",
            body: {
              ...(title === undefined ? {} : { title }),
              ...(pinned === undefined ? {} : { pinned }),
            },
          },
        ),
      );
    },
    async archive({ projectId, threadId }) {
      return ChatThreadResponseSchema.parse(
        await chatRequest(
          transport,
          `${threadPath(projectId)}/${encodeURIComponent(threadId)}/archive`,
          { method: "POST" },
        ),
      );
    },
  };
}

/**
 * The fixture adapter, holding its threads in memory for the session.
 *
 * It behaves like the surface it stands in for — create returns the ratified
 * `201` superset, archive is a reversible status flip that returns the updated
 * thread — so switching adapters changes nothing above this line.
 */
export function createFixtureChatThreadsRepository(): ChatThreadsRepository {
  const threads = new Map<string, ChatThread>();
  for (const wire of fixtureThreads) {
    const thread = ChatThreadListResponseSchema.parse({ data: [wire], meta: {} })
      .threads[0];
    threads.set(thread.id, thread);
  }
  let created = 0;

  function put(thread: ChatThread): ChatThread {
    const next = { ...thread, updatedAt: new Date().toISOString() };
    threads.set(next.id, next);
    return next;
  }

  return {
    async list({ projectId, status }) {
      const wanted = status ?? "active";
      return {
        threads: [...threads.values()]
          .filter((thread) => thread.projectId === projectId)
          .filter((thread) =>
            wanted === "archived"
              ? thread.status === "archived"
              : thread.status !== "archived",
          ),
        nextCursor: null,
      };
    },
    async create({ projectId, title }) {
      created += 1;
      const id = `thread-local-${created}`;
      return put({
        id,
        title: title?.trim() ? title.trim() : null,
        href: `/projects/${projectId}/chats/${id}`,
        status: "idle",
        pinned: false,
        projectId,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        // A locally-created thread has no durable speaker projection behind it
        // yet, and `null` is exactly that: not derived. Never `{state: null}`,
        // which would be a positive claim that this thread holds no design leg.
        designLeg: null,
        discovery: null,
      });
    },
    async update({ threadId, title, pinned }) {
      const thread = threads.get(threadId);
      if (!thread) throw new Error(`no such thread ${threadId}`);
      return put({
        ...thread,
        title: title === undefined ? thread.title : title,
        pinned: pinned === undefined ? thread.pinned : pinned,
      });
    },
    async archive({ threadId }) {
      const thread = threads.get(threadId);
      if (!thread) throw new Error(`no such thread ${threadId}`);
      return put({
        ...thread,
        status: deriveThreadStatus({ archived: true }),
      });
    },
  };
}
