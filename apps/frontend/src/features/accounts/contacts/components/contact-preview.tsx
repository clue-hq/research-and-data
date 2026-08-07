import Link from "next/link";
import { ContactProfileContent } from "../../components/contact-profile-content";
import readability from "../../components/account-readability.module.css";
import type { AccountContactDetail } from "../../model/account-contact";

export function ContactPreview({
  accountId,
  contact,
  onClose,
}: {
  accountId: string;
  contact: AccountContactDetail;
  onClose: () => void;
}) {
  return (
    <aside className="clue-panel-enter fixed inset-y-0 right-0 z-50 flex w-[min(786px,100vw)] flex-col overflow-hidden border-l-[0.5px] border-[var(--clue-border-neutral)] bg-white shadow-[-8px_0_28px_rgba(0,24,62,0.10)]">
      <header className="flex h-[var(--clue-ds-product-dimension-header-action-bar-height)] shrink-0 items-center justify-between border-b-[0.5px] border-[var(--clue-border-neutral)] px-6">
        <div className="flex items-center gap-2">
          <button
            aria-label="Close contact preview"
            className="flex size-6 items-center justify-center rounded-md hover:bg-[var(--clue-background-hover)]"
            onClick={onClose}
            type="button"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              alt=""
              aria-hidden="true"
              className="size-[9px]"
              src="/icons/detail/x.svg"
            />
          </button>
          <span className={readability.uiMedium}>{contact.name}</span>
        </div>
        <div className="flex items-center gap-2">
          <Link
            className={`${readability.actionMedium} flex h-6 items-center gap-1 rounded-md px-1 text-[var(--clue-content-subtle)] hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)]`}
            href={`/accounts/${accountId}/contacts/${contact.id}`}
            scroll={false}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              alt=""
              aria-hidden="true"
              className="size-2.5"
              src="/icons/detail/maximize.svg"
            />
            <span>Open as page</span>
          </Link>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt=""
            aria-hidden="true"
            className="size-3.5"
            src="/icons/detail/link.svg"
          />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt=""
            aria-hidden="true"
            className="h-[2px] w-[10px]"
            src="/icons/detail/ellipsis.svg"
          />
        </div>
      </header>
      <div className="min-h-0 flex-1 overscroll-contain overflow-y-auto [scrollbar-color:#c9ced6_transparent] [scrollbar-gutter:stable] [scrollbar-width:thin]">
        <ContactProfileContent compact contact={contact} />
      </div>
    </aside>
  );
}
