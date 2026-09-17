import {
  SettingsWorkspaceSchema,
  type SettingsWorkspace,
} from "../model/settings";
import { settingsWorkspaceFixture } from "./settings.fixture";

export interface SettingsRepository {
  get(): Promise<SettingsWorkspace>;
}

export const fixtureSettingsRepository: SettingsRepository = {
  async get() {
    return SettingsWorkspaceSchema.parse(settingsWorkspaceFixture);
  },
};

/**
 * Placeholder data for the sections the settings-integration slice binds; never a
 * fallback.
 *
 * Settings → Pages reads its own live surface (`data/pages.repository.ts`); every
 * other section on this shell is still a dummy by ruling until that slice merges,
 * so this returns the fixture unconditionally rather than degrading from HTTP.
 */
export async function getSettingsFixture(): Promise<SettingsWorkspace> {
  return fixtureSettingsRepository.get();
}
