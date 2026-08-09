import { FIXTURE_TRANSPORT, type ChatTransport } from "./chat-api";
import {
  createFixtureChatGatesRepository,
  createHttpChatGatesRepository,
  type ChatGatesRepository,
} from "./chat-gates.repository";
import {
  createFixtureChatMessagesRepository,
  createHttpChatMessagesRepository,
  type ChatMessagesRepository,
} from "./chat-messages.repository";
import {
  createFixtureChatStreamRepository,
  createHttpChatStreamRepository,
  type ChatStreamRepository,
} from "./chat-stream.repository";
import {
  createFixtureChatThreadsRepository,
  createHttpChatThreadsRepository,
  type ChatThreadsRepository,
} from "./chat-threads.repository";
import {
  createFixtureChatTurnsRepository,
  createHttpChatTurnsRepository,
  type ChatTurnsRepository,
} from "./chat-turns.repository";

/**
 * The one place fixture-or-HTTP is chosen for the projects chat flow.
 *
 * Nothing above this file knows which adapter it holds, which is the whole
 * point of `frontend.md`'s seam: `CLUE_PROJECTS_API_BASE_URL` flips every
 * repository at once, and no component, hook, or model changes.
 */
export interface ChatRepositories {
  transport: ChatTransport;
  threads: ChatThreadsRepository;
  messages: ChatMessagesRepository;
  turns: ChatTurnsRepository;
  gates: ChatGatesRepository;
  stream: ChatStreamRepository;
}

export function createChatRepositories(
  transport: ChatTransport = FIXTURE_TRANSPORT,
): ChatRepositories {
  if (transport.mode === "http") {
    return {
      transport,
      threads: createHttpChatThreadsRepository(transport),
      messages: createHttpChatMessagesRepository(transport),
      turns: createHttpChatTurnsRepository(transport),
      gates: createHttpChatGatesRepository(transport),
      stream: createHttpChatStreamRepository(transport),
    };
  }
  return {
    transport,
    threads: createFixtureChatThreadsRepository(),
    messages: createFixtureChatMessagesRepository(),
    turns: createFixtureChatTurnsRepository(),
    gates: createFixtureChatGatesRepository(),
    stream: createFixtureChatStreamRepository(),
  };
}
