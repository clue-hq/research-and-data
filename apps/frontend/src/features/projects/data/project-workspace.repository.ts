import {
  ProjectHomeSchema,
  ProjectRenameResponseSchema,
  type RenamedProject,
  ProjectWorkspaceResponseSchema,
  ProjectWorkspaceSchema,
  type ProjectHome,
  type ProjectWorkspace,
} from "../model/project-workspace";
import {
  projectHomeFixture,
  projectWorkspaceFixture,
} from "./project-workspace.fixture";
import {
  chatRequest,
  resolveChatTransport,
  type ChatTransport,
} from "./chat-api";

export interface ProjectWorkspaceRepository {
  get(projectId: string): Promise<ProjectWorkspace>;
  rename(projectId: string, title: string): Promise<RenamedProject>;
}

export const fixtureProjectWorkspaceRepository: ProjectWorkspaceRepository = {
  async rename() {
    throw new Error("Project renaming requires a connected workspace.");
  },
  async get(projectId) {
    return ProjectWorkspaceSchema.parse({
      ...projectWorkspaceFixture,
      id: projectId,
    });
  },
};

export function createHttpProjectWorkspaceRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ProjectWorkspaceRepository {
  return {
    async rename(projectId, title) {
      return ProjectRenameResponseSchema.parse(
        await chatRequest(transport, `/projects/${encodeURIComponent(projectId)}`, {
          method: "PATCH",
          body: { title },
        }),
      );
    },
    async get(projectId) {
      return ProjectWorkspaceResponseSchema.parse(
        await chatRequest(
          transport,
          `/projects/${encodeURIComponent(projectId)}`,
        ),
      );
    },
  };
}

/** Fixture-only server render for Home; HTTP Home loads through its client repository. */
export function getProjectHome(): Promise<ProjectHome> {
  if (resolveChatTransport().mode === "http") {
    return Promise.resolve(ProjectHomeSchema.parse({
      brands: [],
      composerCapabilities: {
        agentProfileSelection: false,
        attachments: false,
        contextRefs: false,
      },
      defaultAgentProfileId: null,
      defaultBrandId: null,
      entities: [],
      models: [],
      suggestions: [],
    }));
  }
  return Promise.resolve(ProjectHomeSchema.parse(projectHomeFixture));
}

/**
 * A protected Server Component cannot call the origin-relative authenticated
 * BFF. HTTP mode therefore supplies no project payload at all; the client
 * repository loads and validates the real shell before mounting it. This is a
 * loading boundary, never a fixture fallback.
 */
export function getProjectWorkspace(
  projectId: string,
): Promise<ProjectWorkspace | null> {
  if (resolveChatTransport().mode === "http") return Promise.resolve(null);
  return fixtureProjectWorkspaceRepository.get(projectId);
}
