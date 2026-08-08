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

/**
 * Pinned to fixtures until phase 2.
 *
 * The HTTP adapter above calls `api/v1/home` and `api/v1/projects/*`, which no
 * backend serves yet — slice 1 ships the accounts read layer only. It used to
 * flip on `CLUE_API_BASE_URL`, the same variable the accounts flow read, so
 * pointing the app at a real backend to see accounts also threw the home route
 * on the first non-2xx. The accounts flow now owns
 * `CLUE_ACCOUNTS_API_BASE_URL`, and this one stays on fixtures until the
 * project surface exists and gets its own variable.
 */
function getRepository() {
  return fixtureProjectWorkspaceRepository;
}

export function getProjectHome() {
  return getRepository().getHome();
}

export function getProjectWorkspace(projectId: string) {
  return getRepository().getProject(projectId);
}
