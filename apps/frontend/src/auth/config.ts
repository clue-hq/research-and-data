const TRUE = "true";
const LOCAL_APP_ORIGIN = "http://localhost:3000";

/** A deployment/configuration fault that is safe to classify without leaking its message. */
export class ClueConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ClueConfigurationError";
  }
}

/** B3 stays opt-in until B5 cuts every legacy trusted-header surface over. */
export function isAuthenticationEnabled(): boolean {
  return process.env.CLUE_AUTH_ENABLED?.trim().toLowerCase() === TRUE;
}

export function clueApiBaseUrl(): string {
  const configured = process.env.CLUE_API_BASE_URL?.trim();
  if (!configured) {
    throw new ClueConfigurationError(
      "CLUE_API_BASE_URL is required when CLUE_AUTH_ENABLED=true",
    );
  }
  return configured.replace(/\/+$/, "");
}

/** The design (lumen) API origin — server-side only, reached via /api/clue/design. */
export function lumenApiBaseUrl(): string {
  const configured = process.env.LUMEN_API_BASE_URL?.trim();
  if (!configured) {
    throw new ClueConfigurationError(
      "LUMEN_API_BASE_URL is required to proxy the design API",
    );
  }
  return configured.replace(/\/+$/, "");
}

/** The canonical browser origin allowed to perform authenticated BFF mutations. */
export function clueAppOrigin(): string {
  const configured = process.env.CLUE_APP_ORIGIN?.trim();
  if (!configured && process.env.NODE_ENV === "production") {
    throw new Error("CLUE_APP_ORIGIN is required in production when authentication is enabled");
  }
  const value = configured || LOCAL_APP_ORIGIN;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("CLUE_APP_ORIGIN must be an absolute http(s) origin");
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash ||
    value.replace(/\/$/, "") !== parsed.origin
  ) {
    throw new Error("CLUE_APP_ORIGIN must be an absolute http(s) origin without a path");
  }
  return parsed.origin;
}

/** Wave 2 Contract 9: the site editor's domain suffix (`<label>.<suffix>`). Empty = no editor
 * domain is configured; a site then shows the canvas error state. */
export function siteEditorSuffix(): string {
  return process.env.CLUE_SITE_EDITOR_SUFFIX?.trim().toLowerCase() ?? "";
}

function configuredAuthorizedParties(raw: string): string[] {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.every((value) => typeof value === "string")) {
      return parsed.map((value) => value.trim()).filter(Boolean);
    }
  } catch {
    // Shell-safe comma-separated form is the backend's other supported representation.
  }
  return raw.split(",").map((value) => value.trim()).filter(Boolean);
}

function requireMatchingAuthorizedParty(): void {
  const raw = process.env.CLUE_AUTH_CLERK_AUTHORIZED_PARTIES?.trim();
  if (!raw) return;
  const appOrigin = clueAppOrigin();
  if (!configuredAuthorizedParties(raw).includes(appOrigin)) {
    throw new Error(
      "CLUE_APP_ORIGIN must be listed in CLUE_AUTH_CLERK_AUTHORIZED_PARTIES",
    );
  }
}

export function requireAuthenticationConfiguration(): void {
  if (!isAuthenticationEnabled()) return;
  const missing = [
    [
      "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
      process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
    ],
    ["CLERK_SECRET_KEY", process.env.CLERK_SECRET_KEY],
    ["CLUE_API_BASE_URL", process.env.CLUE_API_BASE_URL],
  ]
    .filter(([, value]) => !value?.trim())
    .map(([name]) => name);
  if (missing.length > 0) {
    throw new ClueConfigurationError(
      `CLUE_AUTH_ENABLED=true requires configuration: ${missing.join(", ")}`,
    );
  }
  clueAppOrigin();
  requireMatchingAuthorizedParty();
}
