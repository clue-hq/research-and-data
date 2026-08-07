import {
  ProjectHomeSchema,
  ProjectWorkspaceSchema,
  type ProjectHome,
  type ProjectWorkspace,
} from "../model/project-workspace";
import {
  projectHomeFixture,
  projectWorkspaceFixture,
} from "./project-workspace.fixture";

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
      return ProjectHomeSchema.parse(await read("api/v1/home"));
    },
    async getProject(projectId) {
      return ProjectWorkspaceSchema.parse(
        await read(`api/v1/projects/${encodeURIComponent(projectId)}`),
      );
    },
  };
}

function getRepository() {
  const apiBaseUrl = process.env.CLUE_API_BASE_URL;
  return apiBaseUrl
    ? createHttpProjectWorkspaceRepository(apiBaseUrl)
    : fixtureProjectWorkspaceRepository;
}

export function getProjectHome() {
  return getRepository().getHome();
}

export function getProjectWorkspace(projectId: string) {
  return getRepository().getProject(projectId);
}
