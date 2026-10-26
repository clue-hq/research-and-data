import {
  fetchRead,
  type AuthenticatedReadRequest,
} from "@/features/accounts/data/frontend-api";
import { CrmProviderSchema, type CrmProvider } from "../model/crm";
import {
  CrmIntegrationSchema,
  CrmResearchStateSchema,
  type CrmIntegration,
  type CrmResearchState,
} from "../model/crm-settings";
import {
  CRM_FIXTURE_VARIANTS,
  crmIntegrationFixture,
  withFixtureVariants,
  type CrmFixtureVariant,
} from "./crm-settings.fixtures";

/**
 * The Settings page's server read of `GET /frontend/v1/crm/integration`, through the
 * authenticated read seam (the same one every Settings section uses).
 *
 * Like `workspace.repository.ts`, this module does not import `server-only` so `node:test` can
 * load it; only server code (the settings route's `settings-read.ts`) may import it.
 */

/**
 * The one place `CLUE_CRM_SETTINGS_FIXTURE` is read: `<provider>:<state>[:<variant>…]` (e.g.
 * `salesforce:permission_needed`, `hubspot:ready:expired`, `hubspot:ready:member`) serves that
 * fixture instead of the backend, for checking a state the live data cannot produce. Opt-in and development only — unset, malformed or
 * `NODE_ENV=production` means live, and a failed live read never falls back to it.
 */
export function crmSettingsFixtureSelection(
  value: string | undefined = process.env.CLUE_CRM_SETTINGS_FIXTURE,
  nodeEnv: string | undefined = process.env.NODE_ENV,
): { provider: CrmProvider; state: CrmResearchState; variants: CrmFixtureVariant[] } | null {
  // A production page never shows fixture data: its actions would reach the real CRM.
  if (nodeEnv === "production") return null;
  const [provider, state, ...rest] = (value ?? "").trim().split(":");
  const parsedProvider = CrmProviderSchema.safeParse(provider);
  const parsedState = CrmResearchStateSchema.safeParse(state);
  const variants = rest.filter((variant): variant is CrmFixtureVariant =>
    (CRM_FIXTURE_VARIANTS as readonly string[]).includes(variant),
  );
  if (variants.length !== rest.length || !parsedProvider.success || !parsedState.success) {
    return null;
  }
  return { provider: parsedProvider.data, state: parsedState.data, variants };
}

export async function readCrmIntegration(
  request?: AuthenticatedReadRequest,
): Promise<CrmIntegration> {
  const fixture = crmSettingsFixtureSelection();
  if (fixture !== null) {
    return withFixtureVariants(
      crmIntegrationFixture(fixture.state, fixture.provider),
      fixture.variants,
    );
  }
  return CrmIntegrationSchema.parse(await fetchRead("/crm/integration", {}, request));
}
