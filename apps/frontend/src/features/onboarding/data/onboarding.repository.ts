import {
  OnboardingFlowSchema,
  type OnboardingFlow,
} from "../model/onboarding";
import { onboardingFixture } from "./onboarding.fixture";

export interface OnboardingRepository {
  getFlow(): Promise<OnboardingFlow>;
}

export const fixtureOnboardingRepository: OnboardingRepository = {
  async getFlow() {
    return OnboardingFlowSchema.parse(onboardingFixture);
  },
};

export function createHttpOnboardingRepository(
  apiBaseUrl: string,
): OnboardingRepository {
  const baseUrl = `${apiBaseUrl.replace(/\/$/, "")}/`;

  return {
    async getFlow() {
      const response = await fetch(new URL("api/v1/onboarding", baseUrl), {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });

      if (!response.ok) {
        throw new Error(`Onboarding API returned ${response.status}`);
      }

      return OnboardingFlowSchema.parse(await response.json());
    },
  };
}

export function getOnboardingFlow() {
  const apiBaseUrl = process.env.CLUE_API_BASE_URL;
  const repository = apiBaseUrl
    ? createHttpOnboardingRepository(apiBaseUrl)
    : fixtureOnboardingRepository;

  return repository.getFlow();
}
