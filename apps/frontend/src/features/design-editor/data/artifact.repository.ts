import {
  ChatShellArtifactSchema,
  DesignArtifactListItemSchema,
  DesignArtifactListWireSchema,
  DesignArtifactWireSchema,
  type ChatShellArtifact,
  type DesignArtifactListItem,
} from "../model/artifact";

/** A typed refusal from the artifact seam (envelope code + HTTP status). */
export class DesignArtifactError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(message: string, options: { code: string; status: number }) {
    super(message);
    this.name = "DesignArtifactError";
    this.code = options.code;
    this.status = options.status;
  }
}

export interface DesignArtifactRepository {
  get(projectId: string, artifactId: string): Promise<ChatShellArtifact>;
  /**
   * The project's design-artifact feed, newest-updated first — the gallery's
   * list read. A project with no design legs has no artifacts, which is an
   * empty list, not a refusal.
   */
  list(projectId: string): Promise<DesignArtifactListItem[]>;
}

const FIXTURE_ARTIFACTS: readonly DesignArtifactListItem[] = [
  DesignArtifactListItemSchema.parse({
    id: "doc_web_fixture",
    projectId: "10m-landing-page-campaign",
    documentId: "doc_web_fixture",
    kind: "web",
    title: "Web output",
    currentVersionId: "0",
    status: "draft",
    createdAt: "2026-08-16T09:00:00+00:00",
    updatedAt: "2026-08-16T12:30:00+00:00",
    originThreadId: "thread_fixture",
  }),
];

export function fixtureDesignArtifactRepository(
  artifacts: readonly DesignArtifactListItem[] = FIXTURE_ARTIFACTS,
): DesignArtifactRepository {
  return {
    async get(projectId, artifactId) {
      const artifact = artifacts.find(
        (candidate) =>
          candidate.projectId === projectId && candidate.id === artifactId,
      );
      if (!artifact) {
        throw new DesignArtifactError("no such design artifact", {
          code: "ARTIFACT_NOT_FOUND",
          status: 404,
        });
      }
      // The read seam serves the artifact shape its consumers were written
      // against — the feed's extra fields belong to `list`.
      return ChatShellArtifactSchema.parse(artifact);
    },
    async list(projectId) {
      return artifacts
        .filter((candidate) => candidate.projectId === projectId)
        .sort(
          (left, right) =>
            Date.parse(right.updatedAt) - Date.parse(left.updatedAt),
        );
    },
  };
}

export function httpDesignArtifactRepository({
  baseUrl = "/api/clue",
  fetchImpl,
}: {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
} = {}): DesignArtifactRepository {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  const read = async (path: string): Promise<unknown> => {
    const response = await doFetch(`${baseUrl}${path}`, { cache: "no-store" });
    if (!response.ok) {
      let code = "ARTIFACT_READ_FAILED";
      let message = `design artifact read failed (${response.status})`;
      try {
        const envelope = (await response.json()) as {
          error?: { code?: string; message?: string };
        };
        if (envelope.error?.code) code = envelope.error.code;
        if (envelope.error?.message) message = envelope.error.message;
      } catch {
        // A non-JSON refusal keeps the generic message.
      }
      throw new DesignArtifactError(message, {
        code,
        status: response.status,
      });
    }
    return response.json();
  };
  return {
    async get(projectId, artifactId) {
      return DesignArtifactWireSchema.parse(
        await read(
          `/api/v1/projects/${encodeURIComponent(projectId)}/design-artifacts/${encodeURIComponent(artifactId)}`,
        ),
      );
    },
    async list(projectId) {
      return DesignArtifactListWireSchema.parse(
        await read(
          `/api/v1/projects/${encodeURIComponent(projectId)}/design-artifacts`,
        ),
      );
    },
  };
}
