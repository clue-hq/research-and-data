"use client";

import Link from "../../components/research-link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useDrawerTransition } from "../../hooks/use-drawer-transition";
import motion from "../../components/account-motion.module.css";
import { Link2, Maximize2, MoreHorizontal, X } from "lucide-react";
import { useCopyFeedback } from "@/hooks/use-copy-feedback";
import { ContactProfileContent } from "../../components/contact-profile-content";
import readability from "../../components/account-readability.module.css";
import components from "../../components/account-components.module.css";
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
  const router = useRouter();
  const transition = useDrawerTransition();
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) transition.close(onClose);
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  });
  const copy = useCopyFeedback({
    copiedLabel: "Link copied",
    idleLabel: "Copy contact link",
  });

  return (
    <aside
      aria-label={`${contact.name} contact preview`}
      className={`${motion.drawer} ${components.previewDrawer}`}
      data-closing={transition.closing}
      onAnimationEnd={transition.onAnimationEnd}
    >
      <header className="flex h-14 shrink-0 items-center justify-between border-b-[0.5px] border-[var(--clue-border-neutral)] px-6">
        <div className="flex items-center gap-2">
          <button
            aria-label="Close contact preview"
            className={components.iconButton}
            onClick={() => transition.close(onClose)}
            type="button"
          >
            <X aria-hidden="true" className="size-3.5" strokeWidth={1.5} />
          </button>
          <span className={readability.uiMedium}>{contact.name}</span>
        </div>
        <div className="flex items-center gap-2">
          <Link
            className={`${readability.actionMedium} flex h-[var(--clue-ds-product-component-button-sm-height)] items-center gap-[var(--clue-ds-product-component-button-gap)] rounded-[var(--clue-ds-product-component-button-sm-radius)] px-[var(--clue-ds-product-component-button-sm-padding-inline)] text-[var(--clue-content-subtle)] hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)]`}
            href={`/accounts/${accountId}/contacts/${contact.id}`}
            prefetch
            onNavigate={(event) => {
              event.preventDefault();
              transition.close(() => router.push(`/accounts/${accountId}/contacts/${contact.id}`, { scroll: false }));
            }}
            scroll={false}
          >
            <Maximize2 aria-hidden="true" className="size-3.5" strokeWidth={1.5} />
            <span>Open as page</span>
          </Link>
          <button
            aria-label={copy.label}
            className={components.iconButton}
            onClick={copy.copyCurrentUrl}
            title={copy.label}
            type="button"
          >
            <Link2 aria-hidden="true" className="size-4" strokeWidth={1.5} />
          </button>
          <button aria-label="More contact actions" className={components.iconButton} type="button">
            <MoreHorizontal
              aria-hidden="true"
              className="size-4"
              strokeWidth={1.5}
            />
          </button>
        </div>
      </header>
      <div className={components.previewContent}>
        <ContactProfileContent contact={contact} />
      </div>
    </aside>
  );
}
