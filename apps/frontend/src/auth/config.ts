const TRUE = "true";

/** B3 stays opt-in until B5 cuts every legacy trusted-header surface over. */
export function isAuthenticationEnabled(): boolean {
  return process.env.CLUE_AUTH_ENABLED?.trim().toLowerCase() === TRUE;
}

export function clueApiBaseUrl(): string {
  const configured = process.env.CLUE_API_BASE_URL?.trim();
  if (!configured) {
    throw new Error(
      "CLUE_API_BASE_URL is required when CLUE_AUTH_ENABLED=true",
    );
  }
  return configured.replace(/\/+$/, "");
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
    throw new Error(
      `CLUE_AUTH_ENABLED=true requires configuration: ${missing.join(", ")}`,
    );
  }
}
