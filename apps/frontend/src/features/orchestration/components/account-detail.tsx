"use client";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { AccountPlan } from "../model/workspace";
import { person } from "../model/workspace";
import type { WorkspaceController } from "../hooks/use-workspace";
import type { DirectMailState } from "@/features/direct-mail/model/direct-mail";
import { DetailPanel, Avatar, Status } from "./workspace-ui";
import { artifactVersion } from "../model/artifact-version";
import s from "./workspace.module.css";

export function AccountDetail({ account: a, controller: c, mail, close }: { account: AccountPlan; controller: WorkspaceController; mail: DirectMailState | null; close: () => void }) {
  const data = c.data!, sender = person(data, a.senderId), email = data.emails.find((e) => e.accountId === a.id)!;
  const mailer = mail?.mailers.find((m) => m.id === a.mailerId);
  return <DetailPanel title={a.name} description={`${a.industry} · ${a.territory} territory · Fit ${a.fit}`} close={close}>
    {c.error ? <p className={s.error} role="alert">{c.error}</p> : null}
    <section className={s.section}><div className={s.between}><h2>Account plan</h2><span className={s.tag}>{a.approach}</span></div><p className={s.messageText}>{a.rationale}</p></section>
    <section className={s.section}><h2>Ownership & sending identity</h2><div className={s.grid2}><label className={s.field}>Account owner<select value={a.ownerId} disabled={c.pending} onChange={(e) => void c.run(() => c.repository!.updateAccountOwner(a.id, a.revision, e.target.value))}>{data.people.filter((p) => p.canSend).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><div><p className={s.caption}>Prepared sender</p><div className={`${s.row} mt-2`}><Avatar person={sender} /><span>{sender.name}</span></div></div></div><p className={`${s.caption} mt-3`}>{a.assignmentReason}. Owner changes leave existing sender approvals unchanged.</p>{mailer ? <p className={`${s.caption} mt-2`}>Gift signed by {mailer.signature.replaceAll("\n", " · ")}</p> : null}<p className={`${s.caption} mt-2`}>Project & campaign owner: {person(data, data.project.ownerId).name}</p></section>
    <section className={s.section}><h2>Why this account, now</h2><p className="font-medium text-[13px] mb-3">{a.insight}</p><blockquote className={s.callout}>{a.evidence}</blockquote><p className={`${s.caption} mt-3`}>{a.source} · {a.observedAt}</p></section>
    <section className={s.section}><h2>Buying team</h2>{a.committee.map((p) => <div className={`${s.between} py-3`} key={p.role}><div><p className="text-[13px]">{p.name}</p><p className={s.caption}>{p.role}</p></div><span className={s.caption}>{p.status}</span></div>)}</section>
    <section className={s.section}><h2>The approach</h2>{[
      { title: "Ground the message", detail: "Use the account finding and the recipient’s professional context.", href: null },
      { title: a.mailerId ? "A thoughtful physical introduction" : "Lead with a useful account example", detail: a.mailerId ? "Review the selected gift, handwritten note and itemized cost." : "A personal email and a relevant page. No gifting step is required.", href: a.mailerId ? `/direct-mail/${a.mailerId}` : `/email?message=${email.id}` },
      { title: "Continue from the right person", detail: `${person(data, email.senderId).name} · ${email.trigger.toLowerCase()}. Human replies stop the sequence.`, href: `/email?message=${email.id}` },
    ].map((step, index) => <div className={s.step} key={step.title}><span className={s.stepNumber}>{index + 1}</span><div>{step.href ? <Link className={s.textLink} href={step.href}>{step.title}<ArrowUpRight size={12} /></Link> : <span>{step.title}</span>}<p>{step.detail}</p></div></div>)}</section>
    <section className={s.section}><h2>Connected assets</h2>{data.artifacts.filter((asset) => asset.accountId === a.id).map((asset) => <Link href={`/artifacts?asset=${asset.id}`} className={`${s.between} py-3`} key={asset.id}><span className="text-[13px]">{asset.title}</span><span className={s.caption}>{asset.kind} · v{artifactVersion(asset, data, mail)} ↗</span></Link>)}</section>
    <section className={s.section}><h2>LinkedIn audience</h2><Status tone={a.audienceSize >= 300 ? "neutral" : "warm"}>{a.audienceSize >= 300 ? "Eligible in sample forecast" : "Audience too small"}</Status><p className={`${s.caption} mt-2`}>{a.audienceSize.toLocaleString()} estimated members · 300 minimum. {a.audienceSize < 300 ? "Use a relevant account cohort or keep this approach to personal outreach." : "Confirm the actual audience and media budget before launch."}</p></section>
  </DetailPanel>;
}
