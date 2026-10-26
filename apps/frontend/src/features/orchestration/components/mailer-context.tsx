"use client";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { useWorkspace } from "../hooks/use-workspace";
import { person, projectHref } from "../model/workspace";
import { Avatar } from "./workspace-ui";
import s from "./workspace.module.css";
export function MailerAccountContext({ mailerId }: { mailerId: string }) {
  const { data } = useWorkspace();
  const account = data?.accounts.find((a) => a.mailerId === mailerId);
  if (!data || !account) return null;
  const email = data.emails.find((e) => e.accountId === account.id);
  return <section className={`${s.card} mb-6`} aria-label="Connected account plan"><div className={`${s.between} ${s.wrap}`}><div className={s.row}><Avatar person={person(data,account.ownerId)} small /><span className="text-[12px]">{person(data,account.ownerId).name} · Account owner</span><span className={s.tag}>{account.territory}</span></div><Link className={`${s.textLink} text-[12px]`} href={`${projectHref}?account=${account.id}`}>Account plan<ArrowUpRight size={12} /></Link></div><div className={`${s.row} ${s.wrap} mt-3 text-[12px]`}><Link className={s.textLink} href={`/artifacts?asset=page-${account.id}`}>Landing page preview ↗</Link><span className={s.caption}>·</span>{email ? <Link className={s.textLink} href={`/email?message=${email.id}`}>{email.status === "reply" ? "Open recipient reply" : "Review connected email"} ↗</Link> : null}<span className={s.caption}>·</span><span className={s.caption}>Campaign owner: {person(data,data.project.ownerId).name}</span></div></section>;
}
