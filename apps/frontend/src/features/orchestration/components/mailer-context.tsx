"use client";

import Link from "next/link";
import { useWorkspace } from "../hooks/use-workspace";
import { person, projectHref } from "../model/workspace";
import s from "./workspace.module.css";

export function MailerAccountContext({ mailerId }: { mailerId: string }) {
  const { data } = useWorkspace();
  const account = data?.accounts.find((item) => item.mailerId === mailerId);
  if (!data || !account) return null;
  return <section className={s.mailerContext} aria-label="Project context">
    <Link href={`${projectHref}?account=${account.id}`}>{account.name}</Link>
    <span className={s.caption}>Account owner: {person(data, account.ownerId).name}</span>
    <Link href={`${projectHref}?account=${account.id}&preview=page`}>Landing page</Link>
  </section>;
}
