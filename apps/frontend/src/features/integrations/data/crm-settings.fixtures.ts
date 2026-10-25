import type { CrmProvider } from "../model/crm";
import type {
  CrmIntegration,
  CrmResearchState,
  CrmSetupItem,
  CrmSetupItemStatus,
} from "../model/crm-settings";

/**
 * A `GET /crm/integration` payload in each research state, worded exactly as the backend words it
 * (`crm/settings_view.py`). For the fixture adapter and tests only — never a live fallback.
 */

const NAMES: Record<CrmProvider, string> = { hubspot: "HubSpot", salesforce: "Salesforce" };
const RECORD: Record<CrmProvider, string> = { hubspot: "company", salesforce: "account" };
const PLURAL: Record<CrmProvider, string> = { hubspot: "companies", salesforce: "accounts" };

type Statuses = [CrmSetupItemStatus, CrmSetupItemStatus, CrmSetupItemStatus, CrmSetupItemStatus];

function items(provider: CrmProvider, statuses: Statuses): CrmSetupItem[] {
  const [research, profile, roles, fit] = statuses;
  return [
    {
      key: "company_research_links",
      title: "Company research links",
      description: `A link on each ${RECORD[provider]} record to its research in Clue.`,
      status: research,
    },
    {
      key: "contact_profile_links",
      title: "Contact profile links",
      description: "A link on each contact record to the person’s Clue profile.",
      status: profile,
    },
    {
      key: "contact_buying_roles",
      title: "Contacts’ buying roles",
      description: "The person’s role in the buying decision, saved on their contact record.",
      status: roles,
    },
    {
      key: "company_fit",
      title: "Company fit",
      description: "High, Medium, or Low fit, saved in the “Clue fit level” field.",
      status: fit,
    },
  ];
}

const AT = "2026-10-22T09:30:00+00:00";

export function crmIntegrationFixture(
  state: CrmResearchState,
  provider: CrmProvider,
): CrmIntegration {
  const crm = NAMES[provider];
  const research = {
    state,
    failedField: null as string | null,
    reason: null as string | null,
    reviewChat: null as CrmIntegration["research"]["reviewChat"],
    items: items(provider, ["pending", "pending", "pending", "pending"]),
  };
  switch (state) {
    case "approval_needed":
      research.reviewChat = {
        projectId: "prj_fixture",
        threadId: "thr_fixture",
      };
      break;
    case "preparing":
      break;
    case "ready":
      research.items = items(provider, ["created", "created", "created", "created"]);
      break;
    case "needs_attention":
      research.items = items(provider, ["missing", "created", "created", "created"]);
      research.failedField = "Clue research link";
      research.reason = `Clue’s field “Clue research link” was deleted in ${crm}.`;
      break;
    case "permission_needed":
      research.items = items(provider, ["created", "created", "permission_needed", "created"]);
      research.reason = `The connected ${crm} user doesn’t have permission to create fields on contact records.`;
      break;
    case "couldnt_finish":
      research.items = items(provider, ["created", "created", "pending", "pending"]);
      research.reason = `${crm} stopped part of the setup. Clue can retry the remaining steps.`;
      break;
    case "not_connected":
      // With nothing connected the backend words the items for HubSpot whatever was asked.
      return {
        connection: null,
        canManage: true,
        research: { ...research, items: items("hubspot", ["pending", "pending", "pending", "pending"]) },
        permissions: [],
        overwrites: "ask",
        askClueProjectId: "prj_fixture",
      };
  }
  return {
    connection: {
      provider,
      status: "active",
      accountLabel: provider === "hubspot" ? "Portal 21436587" : "Clue workspace",
      connectedByName: "Aryan",
      connectedAt: AT,
    },
    canManage: true,
    research,
    permissions: [
      {
        grantId: "6f1d6c39-5b1a-4a43-9d3f-6a1c2b7e8f01",
        description: `Always set Clue fit level on ${PLURAL[provider]}`,
        grantedByName: "Aryan",
        grantedAt: AT,
      },
      {
        grantId: "0c2e7a55-31b4-4f6e-8a9d-2b5f4c7d9e02",
        description: "Always add records to Clue lists and campaigns",
        grantedByName: "Aryan",
        grantedAt: AT,
      },
    ],
    overwrites: "ask",
    askClueProjectId: "prj_fixture",
  };
}
