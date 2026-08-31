import {
  OnboardingFlowSchema,
  ProvisionedWorkspaceSchema,
  ProvisionWorkspaceInputSchema,
  type OnboardingFlow,
  type ProvisionWorkspaceInput,
  type ProvisionedWorkspace,
} from "../model/onboarding";
import { onboardingFixture } from "./onboarding.fixture";

/**
 * The onboarding flow copy (titles, labels, role options, setup checklist art) is
 * frontend-owned and always served from the fixture — the earlier `GET /api/v1/onboarding`
 * HTTP read is retired per FI-4 D-7 (serving button copy over HTTP earned nothing, and its
 * direct-origin fetch crashed every auth-configured environment).
 */
export interface OnboardingRepository {
  getFlow(): Promise<OnboardingFlow>;
}

export const fixtureOnboardingRepository: OnboardingRepository = {
  async getFlow() {
    return OnboardingFlowSchema.parse(onboardingFixture);
  },
};

export function getOnboardingFlow(): Promise<OnboardingFlow> {
  return fixtureOnboardingRepository.getFlow();
}

export class OnboardingProvisionError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(message: string, options: { code: string; status: number }) {
    super(message);
    this.name = "OnboardingProvisionError";
    this.code = options.code;
    this.status = options.status;
  }
}

/**
 * FI-4 D-2 over the same-origin server route (`/api/onboarding/provision`), which resolves the
 * Clerk session token server-side and forwards to the backend `POST /auth/v1/provision`.
 * Replay-safe: the backend returns the same workspace for a retried call.
 */
export async function provisionWorkspace(
  input: ProvisionWorkspaceInput,
): Promise<ProvisionedWorkspace> {
  const body = ProvisionWorkspaceInputSchema.parse(input);
  const response = await fetch("/api/onboarding/provision", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) {
    let code = "HTTP_ERROR";
    let message =
      response.status === 422
        ? "Please check your details and try again."
        : `Provisioning failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as {
        error?: { code?: string; message?: string };
      };
      if (payload.error?.code) code = payload.error.code;
      if (payload.error?.message) message = payload.error.message;
    } catch {
      // Non-JSON error body (e.g. FastAPI's bare 422 detail); keep the friendly message.
    }
    throw new OnboardingProvisionError(message, { code, status: response.status });
  }
  return ProvisionedWorkspaceSchema.parse(await response.json());
}

/** Fixture twin used when authentication is off: no network, deterministic ids. */
export async function provisionWorkspaceFixture(
  input: ProvisionWorkspaceInput,
): Promise<ProvisionedWorkspace> {
  return ProvisionedWorkspaceSchema.parse({
    user_id: "usr_fixture",
    workspace_id: "ws_fixture",
    brand_id: "brd_fixture",
    membership_id: "wsm_fixture",
    role_key: "owner",
    company_name: input.company_name,
    company_website: input.company_website,
    first_name: input.first_name,
    last_name: input.last_name,
    job_role: input.job_role,
    created: true,
  });
}
