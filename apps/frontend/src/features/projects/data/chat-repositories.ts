import { FIXTURE_TRANSPORT, type ChatTransport } from "./chat-api";
import { createFixtureChatState } from "./chat-fixture-state";
import {
  createHttpComposerContextRepository,
  unavailableComposerContextRepository,
  type ComposerContextRepository,
} from "./composer-context.repository";
import {
  createFixtureChatGatesRepository,
  createHttpChatGatesRepository,
  type ChatGatesRepository,
} from "./chat-gates.repository";
import {
  createFixtureChatInspectorRepository,
  createHttpChatInspectorRepository,
  type ChatInspectorRepository,
} from "./chat-inspector.repository";
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
import {
  createFixtureProjectHomeRepository,
  createHttpProjectHomeRepository,
  type ProjectHomeRepository,
} from "./project-home.repository";
import {
  createHttpProjectWorkspaceRepository,
  fixtureProjectWorkspaceRepository,
  type ProjectWorkspaceRepository,
} from "./project-workspace.repository";
import {
  createHttpSidebarProjectsRepository,
  fixtureSidebarProjectsRepository,
  type SidebarProjectsRepository,
} from "./sidebar-projects.repository";

/**
 * The one place fixture-or-HTTP is chosen for the projects chat flow.
 *
 * Nothing above this file knows which adapter it holds, which is the whole
 * point of `frontend.md`'s seam: `CLUE_PROJECTS_API_BASE_URL` flips every
 * repository at once, and no component, hook, or model changes.
 */
export interface ChatRepositories {
  transport: ChatTransport;
  home: ProjectHomeRepository;
  projects: ProjectWorkspaceRepository;
  sidebar: SidebarProjectsRepository;
  threads: ChatThreadsRepository;
  messages: ChatMessagesRepository;
  turns: ChatTurnsRepository;
  gates: ChatGatesRepository;
  stream: ChatStreamRepository;
  /**
   * The dev-lens turn-context inspector. Present on both transports, but the
   * HTTP adapter's own probe reports it unavailable against any deployment that
   * did not register the routes — which is every production deployment.
   */
  inspector: ChatInspectorRepository;
  composerContext: ComposerContextRepository;
}

export function createChatRepositories(
  transport: ChatTransport = FIXTURE_TRANSPORT,
): ChatRepositories {
  if (transport.mode === "http") {
    return {
      transport,
      home: createHttpProjectHomeRepository(transport),
      projects: createHttpProjectWorkspaceRepository(transport),
      sidebar: createHttpSidebarProjectsRepository(transport),
      threads: createHttpChatThreadsRepository(transport),
      messages: createHttpChatMessagesRepository(transport),
      turns: createHttpChatTurnsRepository(transport),
      gates: createHttpChatGatesRepository(transport),
      stream: createHttpChatStreamRepository(transport),
      inspector: createHttpChatInspectorRepository(transport),
      composerContext: createHttpComposerContextRepository(transport),
    };
  }
  // One shared fixture state, so the four adapters agree with each other the
  // way the one backend they stand in for does.
  const state = createFixtureChatState();
  return {
    transport,
    home: createFixtureProjectHomeRepository(),
    projects: fixtureProjectWorkspaceRepository,
    sidebar: fixtureSidebarProjectsRepository,
    threads: createFixtureChatThreadsRepository(),
    messages: createFixtureChatMessagesRepository(),
    turns: createFixtureChatTurnsRepository(state),
    gates: createFixtureChatGatesRepository(state),
    stream: createFixtureChatStreamRepository(state),
    inspector: createFixtureChatInspectorRepository(),
    composerContext: unavailableComposerContextRepository,
  };
}
