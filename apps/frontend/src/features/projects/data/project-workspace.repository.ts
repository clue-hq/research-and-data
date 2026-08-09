import {
  ProjectHomeSchema,
  ProjectHomeResponseSchema,
  ProjectWorkspaceSchema,
  type ProjectHome,
  type ProjectWorkspace,
} from "../model/project-workspace";
import {
  projectHomeFixture,
  projectWorkspaceFixture,
} from "./project-workspace.fixture";
import { resolveChatTransport } from "./chat-api";

export interface ProjectWorkspaceRepository {
  getHome(): Promise<ProjectHome>;
  getProject(projectId: string): Promise<ProjectWorkspace>;
}

export const fixtureProjectWorkspaceRepository: ProjectWorkspaceRepository = {
  async getHome() {
    return ProjectHomeSchema.parse(projectHomeFixture);
  },
  async getProject(projectId) {
    return ProjectWorkspaceSchema.parse({
      ...projectWorkspaceFixture,
      id: projectId,
    });
  },
};

export function createHttpProjectWorkspaceRepository(
  apiBaseUrl: string,
): ProjectWorkspaceRepository {
  const baseUrl = `${apiBaseUrl.replace(/\/$/, "")}/`;

  async function read(path: string) {
    const response = await fetch(new URL(path, baseUrl), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Project API returned ${response.status}`);
    }
    return response.json();
  }

  return {
    async getHome() {
      return ProjectHomeResponseSchema.parse(await read("api/v1/home"));
    },
    async getProject(projectId) {
      return ProjectWorkspaceSchema.parse(
        await read(`api/v1/projects/${encodeURIComponent(projectId)}`),
      );
    },
  };
}

/**
 * The server-rendered Home shell cannot call the origin-relative authenticated
 * BFF. In HTTP mode it therefore emits a neutral loading model; the client-side
 * Home repository reads `/api/v1/home` through that BFF before enabling Send.
 * Project-shell reads remain fixture-owned until R3.
 */
function getRepository() {
  return fixtureProjectWorkspaceRepository;
}

export function getProjectHome() {
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
  return getRepository().getHome();
}

export function getProjectWorkspace(projectId: string) {
  return getRepository().getProject(projectId);
}
