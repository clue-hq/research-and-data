/**
 * The operator link (2026-10-14): `/onboarding/setting-up?workspace=<id>&website=<url>`.
 *
 * An operator gives an existing user one more workspace (`scripts/provision_additional_workspace.py`),
 * and the user starts its onboarding by opening this link. Both values are required and must be
 * well-formed: a partial or odd link yields no target, and the screen then behaves exactly as it
 * does without one. The workspace is never trusted from here — the screen selects it through the
 * `selectWorkspace` server action, which re-checks membership.
 */
export interface OperatorSetupTarget {
  workspaceId: string;
  companyWebsite: string;
}

const WORKSPACE_ID = /^ws_[A-Za-z0-9]+$/;
const HTTP_WEBSITE = /^https?:\/\/[^\s/?#]+\.[^\s/?#]+(?:[/?#]\S*)?$/i;

function single(value: string | string[] | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

export function operatorSetupTarget(params: {
  workspace?: string | string[];
  website?: string | string[];
}): OperatorSetupTarget | null {
  const workspaceId = single(params.workspace);
  const companyWebsite = single(params.website);
  if (!WORKSPACE_ID.test(workspaceId) || !HTTP_WEBSITE.test(companyWebsite)) return null;
  return { workspaceId, companyWebsite };
}
