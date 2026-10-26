import { FIXTURE_TRANSPORT, type ChatTransport } from "./chat-api";
import { createFixtureChatState } from "./chat-fixture-state";
import {
  createHttpComposerContextRepository,
  unavailableComposerContextRepository,
  type ComposerContextRepository,
} from "./composer-context.repository";
import {
  createHttpMentionDirectoryRepository,
  unavailableMentionDirectoryRepository,
  type MentionDirectoryRepository,
} from "./mention-directory.repository";
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
  createFixtureChatThreadStreamRepository,
  createHttpChatThreadStreamRepository,
  type ChatThreadStreamRepository,
} from "./chat-thread-stream.repository";
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
  createFixtureDiscoveryRunsRepository,
  createHttpDiscoveryRunsRepository,
  type DiscoveryRunsRepository,
} from "./discovery-runs.repository";
import {
  createFixtureProjectDirectoryRepository,
  createHttpProjectDirectoryRepository,
  type ProjectDirectoryRepository,
} from "./project-directory.repository";
import {
  createFixtureProjectHomeRepository,
  createHttpProjectHomeRepository,
  type ProjectHomeRepository,
} from "./project-home.repository";
import {
  createFixtureProjectInstructionsRepository,
  createHttpProjectInstructionsRepository,
  type ProjectInstructionsRepository,
} from "./project-instructions.repository";
import {
  createFixtureProjectMemoryRepository,
  createHttpProjectMemoryRepository,
  type ProjectMemoryRepository,
} from "./project-memory.repository";
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
  /** The projects directory: the whole list, its creation, and its shelving. */
  directory: ProjectDirectoryRepository;
  /** One project's standing instructions document. */
  instructions: ProjectInstructionsRepository;
  /** One project's scope memory, written through the backend's one seam. */
  memory: ProjectMemoryRepository;
  sidebar: SidebarProjectsRepository;
  threads: ChatThreadsRepository;
  messages: ChatMessagesRepository;
  turns: ChatTurnsRepository;
  gates: ChatGatesRepository;
  stream: ChatStreamRepository;
  /** The thread's lifecycle frames, so an open chat follows turns it did not start. */
  threadStream: ChatThreadStreamRepository;
  /** Stop for the account discovery a thread is holding busy. */
  discoveries: DiscoveryRunsRepository;
  /**
   * The dev-lens turn-context inspector. Present on both transports, but the
   * HTTP adapter's own probe reports it unavailable against any deployment that
   * did not register the routes — which is every production deployment.
   */
  inspector: ChatInspectorRepository;
  composerContext: ComposerContextRepository;
  /** The @ tagger's directory: every account and committee contact, names and ids. */
  mentionDirectory: MentionDirectoryRepository;
}

export function createChatRepositories(
  transport: ChatTransport = FIXTURE_TRANSPORT,
): ChatRepositories {
  if (transport.mode === "http") {
    return {
      transport,
      home: createHttpProjectHomeRepository(transport),
      projects: createHttpProjectWorkspaceRepository(transport),
      directory: createHttpProjectDirectoryRepository(transport),
      instructions: createHttpProjectInstructionsRepository(),
      memory: createHttpProjectMemoryRepository(),
      sidebar: createHttpSidebarProjectsRepository(transport),
      threads: createHttpChatThreadsRepository(transport),
      messages: createHttpChatMessagesRepository(transport),
      turns: createHttpChatTurnsRepository(transport),
      gates: createHttpChatGatesRepository(transport),
      stream: createHttpChatStreamRepository(transport),
      threadStream: createHttpChatThreadStreamRepository(transport),
      discoveries: createHttpDiscoveryRunsRepository(transport),
      inspector: createHttpChatInspectorRepository(transport),
      composerContext: createHttpComposerContextRepository(transport),
      mentionDirectory: createHttpMentionDirectoryRepository(transport),
    };
  }
  // One shared fixture state, so the four adapters agree with each other the
  // way the one backend they stand in for does.
  const state = createFixtureChatState();
  return {
    transport,
    home: createFixtureProjectHomeRepository(),
    projects: fixtureProjectWorkspaceRepository,
    directory: createFixtureProjectDirectoryRepository(),
    instructions: createFixtureProjectInstructionsRepository(),
    memory: createFixtureProjectMemoryRepository(),
    sidebar: fixtureSidebarProjectsRepository,
    threads: createFixtureChatThreadsRepository(),
    messages: createFixtureChatMessagesRepository(),
    turns: createFixtureChatTurnsRepository(state),
    gates: createFixtureChatGatesRepository(state),
    stream: createFixtureChatStreamRepository(state),
    threadStream: createFixtureChatThreadStreamRepository(),
    discoveries: createFixtureDiscoveryRunsRepository(),
    inspector: createFixtureChatInspectorRepository(),
    composerContext: unavailableComposerContextRepository,
    mentionDirectory: unavailableMentionDirectoryRepository,
  };
}
