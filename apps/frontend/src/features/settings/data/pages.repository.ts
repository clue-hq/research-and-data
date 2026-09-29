import { fetchRead } from "@/features/accounts/data/frontend-api";

import { PagesSettingsReadSchema, type PagesSettingsRead } from "../model/pages";

/**
 * Read the Settings → Pages control plane off `/frontend/v1/settings/pages`.
 *
 * There is no fixture mode: a misconfigured or unauthorised surface throws
 * `ClueApiError` rather than rendering an empty screen.
 */
export async function getPagesSettings(
  read: typeof fetchRead = fetchRead,
): Promise<PagesSettingsRead> {
  return PagesSettingsReadSchema.parse(await read("/settings/pages"));
}
