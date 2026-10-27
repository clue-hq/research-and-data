"use client";
import Link from "next/link";
import { useWorkspace } from "../hooks/use-workspace";
import { useDirectMail } from "@/features/direct-mail/hooks/use-direct-mail";
import { materialGalleryHref } from "@/features/account-materials/model/materials";
import s from "./workspace.module.css";
export function MailerAccountContext({mailerId}:{mailerId:string}) {
 const {data}=useWorkspace(),mail=useDirectMail();
 const mailer=mail.data?.mailers.find(m=>m.id===mailerId),account=data?.accounts.find(a=>a.id===mailer?.accountId);
 if(!data || !account || !mailer)return null;
 const page=data.artifacts.find(a=>a.kind==="page" && (a.mailerId===mailer.id || (!a.mailerId && a.accountId===account.id)));
 return <section className={s.mailerContext} aria-label="Project context"><Link href={materialGalleryHref(mailer.projectId,account.id)}>{account.name} · All materials</Link><span className={s.caption}>Account owner: {data.people.find(p=>p.id===account.ownerId)?.name}</span>{page?<Link href={materialGalleryHref(mailer.projectId,account.id,page.id)}>Landing page</Link>:null}</section>;
}
