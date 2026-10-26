import { CRM_PROVIDER_NAMES, CrmProviderSchema, type CrmProvider } from "./crm";
import type { CrmConnectMode } from "./crm-settings";

/**
 * The Settings connect flow (Figma board 06 "Connection & confirmation flows", 2310:2264): one
 * modal dialog at a time over the settings page, the CRM's sign-in in a separate window.
 *
 * Connect → choose a CRM → finish (waiting for sign-in) → closed once the connection answers.
 * Reconnect → confirm → finish. Change CRM → confirm → choose (switch mode) → finish. A failed
 * sign-in or a refused click shows the failure with Try again.
 */
export type CrmConnectFlow =
  | { step: "closed" }
  | { step: "choose"; mode: CrmConnectMode }
  | { step: "confirm_reconnect"; provider: CrmProvider }
  | { step: "confirm_change" }
  | { step: "waiting"; mode: CrmConnectMode; provider: CrmProvider; requestId: string }
  | {
      step: "failed";
      mode: CrmConnectMode;
      provider: CrmProvider;
      /** The request a sign-in was already opened for, so Try again reuses it. */
      requestId: string | null;
      message: string;
    };

export type CrmConnectFlowEvent =
  | { type: "start_connect" }
  | { type: "start_reconnect"; provider: CrmProvider }
  | { type: "start_change" }
  | { type: "continue_change" }
  | { type: "opened"; mode: CrmConnectMode; provider: CrmProvider; requestId: string }
  | { type: "failed"; mode: CrmConnectMode; provider: CrmProvider; message: string }
  | { type: "connected" }
  | { type: "cancel" };

export const CRM_CONNECT_FLOW_CLOSED: CrmConnectFlow = { step: "closed" };

export function crmConnectFlowReducer(
  flow: CrmConnectFlow,
  event: CrmConnectFlowEvent,
): CrmConnectFlow {
  switch (event.type) {
    case "start_connect":
      return { step: "choose", mode: "connect" };
    case "start_reconnect":
      return { step: "confirm_reconnect", provider: event.provider };
    case "start_change":
      return { step: "confirm_change" };
    case "continue_change":
      return flow.step === "confirm_change" ? { step: "choose", mode: "switch" } : flow;
    case "opened":
      // A link that arrives after the person cancelled does not reopen the flow.
      if (flow.step === "closed") return flow;
      return {
        step: "waiting",
        mode: event.mode,
        provider: event.provider,
        requestId: event.requestId,
      };
    case "failed":
      // A word that arrives after the person closed the dialog changes nothing.
      if (flow.step === "closed") return flow;
      return {
        step: "failed",
        mode: event.mode,
        provider: event.provider,
        requestId: "requestId" in flow ? flow.requestId : null,
        message: event.message,
      };
    case "connected":
    case "cancel":
      return CRM_CONNECT_FLOW_CLOSED;
  }
}

/** HubSpot connects a portal; Salesforce an organization. */
function accountNoun(provider: CrmProvider): string {
  return provider === "hubspot" ? "portal" : "organization";
}

/** "Connect your CRM" (2310:2266). */
export function crmChooseCopy() {
  return {
    title: "Connect your CRM",
    description: "Choose one CRM for this workspace. You’ll sign in securely in a new window.",
    providers: CrmProviderSchema.options.map((provider) => ({
      provider,
      name: CRM_PROVIDER_NAMES[provider],
      subtitle: `Connect a ${CRM_PROVIDER_NAMES[provider]} ${accountNoun(provider)}`,
    })),
    note: "Only owners and admins can connect a CRM.",
  };
}

/** "Finish connecting in HubSpot" (2310:2324). */
export function crmFinishCopy(provider: CrmProvider) {
  return {
    title: `Finish connecting in ${CRM_PROVIDER_NAMES[provider]}`,
    description: `A sign-in window is open. Choose your ${accountNoun(provider)} and approve access, then return here.`,
    status: "Waiting for sign-in",
  };
}

/**
 * "Reconnect HubSpot" (2310:2347). The account is named in brackets after the CRM's own word for
 * it, so a HubSpot label ("Portal 21436587") never reads "the same Portal … portal".
 */
export function crmReconnectCopy(provider: CrmProvider, accountLabel: string) {
  const name = CRM_PROVIDER_NAMES[provider];
  const account = provider === "hubspot" ? "account" : "organization";
  return {
    title: `Reconnect ${name}`,
    lines: [
      `Sign in to the same ${name} ${account}${accountLabel ? ` (${accountLabel})` : ""} to keep your permissions, pending cards, and history.`,
      `If you choose another ${accountNoun(provider)}, Clue will ask you to confirm the change.`,
    ],
  };
}

/** "Change your CRM?" (2310:2372), for the connected CRM. */
export function crmChangeCopy(provider: CrmProvider) {
  return {
    title: "Change your CRM?",
    description: "Connect a different CRM, portal, or organization.",
    consequence: `Your “Always allow” permissions will be cleared. Changes Clue already made in ${CRM_PROVIDER_NAMES[provider]} will stay there. Cards waiting in chats will be closed.`,
    note: `Reconnecting the same ${accountNoun(provider)} keeps everything.`,
  };
}

/**
 * A connect that did not finish, after "Connection action failed" (07, 2310:2489). An existing
 * connection (reconnect, switch) is untouched by a failed attempt, so it says so.
 */
export function crmFailureCopy(mode: CrmConnectMode, provider: CrmProvider, message: string) {
  const name = CRM_PROVIDER_NAMES[provider];
  return {
    title: mode === "reconnect" ? `Couldn’t reconnect ${name}` : `Couldn’t connect ${name}`,
    message,
    note: mode === "connect" ? null : "Your saved permissions and history are unchanged.",
  };
}
