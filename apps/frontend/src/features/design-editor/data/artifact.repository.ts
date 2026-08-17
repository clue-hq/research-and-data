import {
  ChatShellArtifactSchema,
  DesignArtifactWireSchema,
  type ChatShellArtifact,
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
}

const FIXTURE_ARTIFACTS: readonly ChatShellArtifact[] = [
  ChatShellArtifactSchema.parse({
    id: "doc_web_fixture",
    projectId: "10m-landing-page-campaign",
    documentId: "doc_web_fixture",
    kind: "web",
    title: "Web output",
    currentVersionId: "0",
    status: "draft",
  }),
];

export function fixtureDesignArtifactRepository(
  artifacts: readonly ChatShellArtifact[] = FIXTURE_ARTIFACTS,
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
      return artifact;
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
  return {
    async get(projectId, artifactId) {
      const response = await doFetch(
        `${baseUrl}/api/v1/projects/${encodeURIComponent(projectId)}/design-artifacts/${encodeURIComponent(artifactId)}`,
        { cache: "no-store" },
      );
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
      return DesignArtifactWireSchema.parse(await response.json());
    },
  };
}
