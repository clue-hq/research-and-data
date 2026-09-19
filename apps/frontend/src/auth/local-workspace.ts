import { ClueConfigurationError } from "./config";
import { ClueAuthenticationError } from "./errors";
import { WORKSPACE_COOKIE } from "../features/session/model/session";

type Environment = Readonly<Record<string, string | undefined>>;

export interface LocalWorkspaceInstance {
  workspaceId: string;
  name: string;
  port: string;
  cookieName: string;
  distDir: string;
}

/** Server configuration only. A selector, never an authentication bypass. */
export function localWorkspaceInstance(
  env: Environment = process.env,
): LocalWorkspaceInstance | null {
  const workspaceId = env.CLUE_LOCAL_WORKSPACE_ID?.trim();
  const name = env.CLUE_LOCAL_WORKSPACE_NAME?.trim();
  if (!workspaceId && !name) return null;
  if (
    env.NODE_ENV !== "development" ||
    env.CLUE_AUTH_ENABLED?.trim().toLowerCase() !== "true"
  ) {
    throw new ClueConfigurationError("Local workspace instances require authenticated development mode");
  }
  if (!workspaceId || !/^ws_[a-zA-Z0-9_]+$/.test(workspaceId) || !name || name.length > 80) {
    throw new ClueConfigurationError("Set both CLUE_LOCAL_WORKSPACE_ID and CLUE_LOCAL_WORKSPACE_NAME");
  }
  let origin: URL;
  try {
    origin = new URL(env.CLUE_APP_ORIGIN ?? "");
  } catch {
    throw new ClueConfigurationError("Local workspace instances require a loopback CLUE_APP_ORIGIN with a port");
  }
  if (
    !["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname) ||
    !["http:", "https:"].includes(origin.protocol) || !origin.port ||
    origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash
  ) {
    throw new ClueConfigurationError("Local workspace instances require a loopback CLUE_APP_ORIGIN with a port");
  }
  return {
    workspaceId,
    name,
    port: origin.port,
    cookieName: `${WORKSPACE_COOKIE}_${origin.port}`,
    distDir: `.next-local-${origin.port}`,
  };
}

export function workspaceCookieName(): string {
  return localWorkspaceInstance()?.cookieName ?? WORKSPACE_COOKIE;
}

export function assertLocalWorkspaceSelection(workspaceId: string): void {
  const instance = localWorkspaceInstance();
  if (instance && instance.workspaceId !== workspaceId) {
    throw new ClueAuthenticationError("This local instance is pinned to its workspace", {
      code: "WORKSPACE_FORBIDDEN", status: 403,
    });
  }
}

/** Provisioning replay edits the user's original workspace, not the pinned one. */
export function localProvisioningRefusal(): Response | null {
  if (!localWorkspaceInstance()) return null;
  return Response.json({ error: {
    code: "LOCAL_WORKSPACE_PINNED",
    message: "This local instance uses an existing workspace. Provisioning is disabled here.",
  } }, { status: 403 });
}
