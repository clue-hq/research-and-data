import type { ReactNode } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { X, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import type { AccountPlan, Person } from "../model/workspace";
import { projectHref } from "../model/workspace";
import type { Mailer } from "@/features/direct-mail/model/direct-mail";
import s from "./workspace.module.css";

export function Avatar({ person, small = false }: { person: Pick<Person, "initials" | "name">; small?: boolean }) { return <span className={`${s.avatar} ${small ? s.avatarSmall : ""}`} title={person.name}>{person.initials}</span>; }
export function Status({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "warm" | "green" }) { return <span className={s.status} data-tone={tone}><span />{children}</span>; }
export function AccountMark({ account }: { account: AccountPlan }) { return <span className={s.accountMark}>{account.initials}</span>; }
export function DetailPanel({ title, description, close, children, wide = false }: { title: string; description: string; close: () => void; children: ReactNode; wide?: boolean }) {
  return <Dialog.Root open onOpenChange={(open) => { if (!open) close(); }}><Dialog.Portal><Dialog.Backdrop className={s.backdrop} /><Dialog.Popup className={`${s.drawer} ${wide ? s.drawerWide : ""}`}><header className={s.drawerHeader}><div><Dialog.Title className={s.panelTitle}>{title}</Dialog.Title><Dialog.Description className={s.caption}>{description}</Dialog.Description></div><Button variant="transparent" size="icon-sm" aria-label="Close details" onClick={close}><X size={16} /></Button></header><div className={s.drawerBody}>{children}</div></Dialog.Popup></Dialog.Portal></Dialog.Root>;
}
export function AccountLink({ account }: { account: AccountPlan }) { return <Link href={`${projectHref}?account=${account.id}`} className={s.textLink}>{account.name}<ArrowUpRight size={12} /></Link>; }
export function accountProgress(account: AccountPlan, mailer?: Mailer, hasReply = false) {
  if (hasReply) return { label: "Reply to continue", next: `Respond to ${account.contact.split(" ")[0]}’s request`, tone: "green" as const };
  if (mailer?.stage === "canceled") return { label: "Canceled", next: "Revisit the account approach", tone: "neutral" as const };
  if (mailer && !mailer.addressConfirmed && !mailer.approval) return { label: "Needs an address", next: "Confirm receiving details", tone: "warm" as const };
  if (mailer?.approval) return { label: mailer.stage === "delivered" ? "Delivered" : mailer.stage === "approved" ? "Approved" : "In progress", next: mailer.stage === "approved" ? "Waiting for merchant order" : "Track gift and follow-up", tone: "neutral" as const };
  return { label: "Ready for review", next: account.mailerId ? "Review gift, note and cost" : "Review personal email", tone: "neutral" as const };
}
