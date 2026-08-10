import type { AccountDetail } from "../model/account-detail";
import {
  AccountCoveragePanel,
  AccountDetailsList,
  AccountIdentity,
  AccountTextSection,
  PreviewToolbar,
} from "./account-detail-primitives";

export function AccountPreviewDrawer({
  account,
}: {
  account: AccountDetail;
}) {
  return (
    <aside
      aria-label={`${account.name} account preview`}
      className="clue-panel-enter fixed top-0 right-0 z-30 h-dvh w-[min(727px,100vw)] overflow-hidden bg-white shadow-[-6px_0_18px_rgba(0,24,62,0.08)] before:absolute before:inset-y-0 before:left-0 before:z-40 before:w-px before:bg-[var(--clue-border-neutral)]"
    >
      <PreviewToolbar account={account} />
      <div className="h-[calc(100dvh-48px)] w-full overscroll-contain overflow-y-auto px-8 pb-12 [scrollbar-color:#c9ced6_transparent] [scrollbar-gutter:stable] [scrollbar-width:thin]">
        <div className="mt-12">
          <AccountIdentity account={account} />
        </div>
        <div className="mt-9">
          <AccountDetailsList account={account} showCommittee />
        </div>
        <div className="mt-9">
          <AccountTextSection
            emptyNote="A written account summary is composed once this account's deep research completes."
            title="Account summary"
          />
        </div>
        <div className="mt-9">
          <AccountCoveragePanel account={account} />
        </div>
      </div>
    </aside>
  );
}
