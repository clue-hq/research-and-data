"use client";

import Image from "next/image";
import Link from "next/link";
import { ApplicationShell } from "@/components/shell/application-shell";
import { useCopyFeedback } from "@/hooks/use-copy-feedback";
import type { AccountContactDetail } from "../model/account-contact";
import readability from "./account-readability.module.css";
import { ContactProfileContent } from "./contact-profile-content";

export function ContactFullScreen({
  contact,
}: {
  contact: AccountContactDetail;
}) {
  const copy = useCopyFeedback({
    copiedLabel: "Link copied",
    idleLabel: "Copy contact link",
  });

  return (
    <ApplicationShell activeHref="/accounts">
      <main className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
        <header className="flex h-[var(--clue-ds-product-dimension-header-action-bar-height)] shrink-0 items-center justify-between border-b-[0.5px] border-[var(--clue-border-neutral)] bg-white pr-6 pl-14 lg:px-8">
          <nav
            aria-label="Breadcrumb"
            className={`${readability.uiRegular} clue-scrollbar-hidden flex min-w-0 items-center gap-1 overflow-x-auto`}
          >
            <Link
              className="flex h-7 items-center rounded-md px-2 text-[var(--clue-content-subtle)] hover:bg-[var(--clue-background-hover)]"
              href="/accounts"
            >
              Accounts
            </Link>
            <span className="text-[var(--clue-content-subtle)]">/</span>
            <Link
              className="flex h-7 items-center gap-1.5 rounded-md px-2 hover:bg-[var(--clue-background-hover)]"
              href={`/accounts/${contact.accountId}`}
            >
              <Image
                alt=""
                aria-hidden="true"
                height={12}
                src={contact.accountLogoPath}
                width={12}
              />
              {contact.accountName}
            </Link>
            <span className="text-[var(--clue-content-subtle)]">/</span>
            <span className={`${readability.uiMedium} flex h-7 items-center whitespace-nowrap px-2`}>
              {contact.name}
            </span>
          </nav>
          <div className="ml-4 flex shrink-0 items-center gap-2.5">
            <span className={`${readability.fieldLabel} hidden text-[var(--clue-content-subtle)] sm:inline`}>
              Last updated&nbsp;&nbsp; yesterday
            </span>
            <button
              aria-label={copy.label}
              className="flex size-6 items-center justify-center rounded-md hover:bg-[var(--clue-background-hover)]"
              onClick={copy.copyCurrentUrl}
              title={copy.label}
              type="button"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img alt="" className="size-3.5" src="/icons/detail/link.svg" />
            </button>
            <button
              aria-label="More contact actions"
              className="flex size-6 items-center justify-center rounded-md hover:bg-[var(--clue-background-hover)]"
              type="button"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img alt="" className="h-[2px] w-[10px]" src="/icons/detail/ellipsis.svg" />
            </button>
          </div>
        </header>
        <div className="clue-scrollbar-hidden min-h-0 flex-1 overflow-y-auto">
          <article className="mx-auto w-full max-w-[720px] px-8 pt-12">
            <ContactProfileContent contact={contact} />
          </article>
        </div>
      </main>
    </ApplicationShell>
  );
}
