import {
  ChatMessageListResponseSchema,
  type ChatMessagePage,
} from "../model/chat-message";
import { chatRequest, type ChatTransport } from "./chat-api";
import { fixtureMessages } from "./chat.fixture";

/**
 * The durable transcript read (charter §3.6's cold load).
 *
 * Cold load is a paginated *message* read plus current projections — never an
 * SSE replay of the whole conversation. `includeBodies` is the explicit opt-in
 * the as-built contract adds: the listing is body-free by default and carries
 * only the content address, because a browser cannot issue one artifact fetch
 * per message and a surface that hydrated a whole thread by default would.
 */
export interface ChatMessagesRepository {
  list(input: {
    projectId: string;
    threadId: string;
    limit?: number;
    cursor?: string;
    includeBodies?: boolean;
  }): Promise<ChatMessagePage>;
}

export function createHttpChatMessagesRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ChatMessagesRepository {
  return {
    async list({ projectId, threadId, limit, cursor, includeBodies = true }) {
      return ChatMessageListResponseSchema.parse(
        await chatRequest(
          transport,
          `/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(
            threadId,
          )}/messages`,
          { query: { limit, cursor, include: includeBodies ? "bodies" : undefined } },
        ),
      );
    },
  };
}

export function createFixtureChatMessagesRepository(): ChatMessagesRepository {
  return {
    async list({ threadId, includeBodies = true }) {
      const page = ChatMessageListResponseSchema.parse({
        data: fixtureMessages.filter((message) => message.thread_id === threadId),
        meta: {},
      });
      if (includeBodies) return page;
      // The body-free listing really is body-free: the fixture must not serve
      // words the real default read does not.
      return {
        ...page,
        messages: page.messages.map((message) => ({ ...message, body: null })),
      };
    },
  };
}
