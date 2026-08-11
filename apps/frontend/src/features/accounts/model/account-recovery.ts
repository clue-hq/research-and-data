export type AccountRecoveryKind =
  | "session_expired"
  | "workspace_selection"
  | "forbidden"
  | "service_unavailable"
  | "contract_error";

export type AccountRecovery = Readonly<{
  kind: AccountRecoveryKind;
  requestId: string | null;
  retryable: boolean;
}>;

export const ACCOUNT_RECOVERY_COPY: Readonly<
  Record<AccountRecoveryKind, Readonly<{ body: string; title: string }>>
> = {
  session_expired: {
    title: "Your session has expired",
    body: "Sign in again to securely reopen Accounts.",
  },
  workspace_selection: {
    title: "Choose a workspace",
    body: "Accounts needs an active workspace selection before it can load data.",
  },
  forbidden: {
    title: "You don’t have access to this workspace",
    body: "Your account is signed in, but it cannot read Accounts for the selected workspace.",
  },
  service_unavailable: {
    title: "Accounts is temporarily unavailable",
    body: "The Account service could not be reached. Your workspace data has not been changed.",
  },
  contract_error: {
    title: "Accounts needs support",
    body: "The Account service returned a response this version of Clue cannot safely use.",
  },
};
