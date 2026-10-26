"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Search, Package, MessageSquare, FileText } from "lucide-react";
import type { WorkspaceState } from "../model/workspace";
import { person, projectHref } from "../model/workspace";
import type { DirectMailState } from "@/features/direct-mail/model/direct-mail";
import { AccountMark, Avatar, Status, accountProgress } from "./workspace-ui";
import s from "./workspace.module.css";

export function ProjectPlan({ data, mail }: { data: WorkspaceState; mail: DirectMailState | null }) {
  const [search, setSearch] = useState(""), [owner, setOwner] = useState("all"), [approach, setApproach] = useState("all");
  const accounts = data.accounts.filter((a) => (owner === "all" || a.ownerId === owner) && (approach === "all" || a.approach === approach) && `${a.name} ${a.contact}`.toLowerCase().includes(search.toLowerCase()));
  const drafts = data.emails.filter((e) => e.status === "draft").length;
  const reply = data.emails.filter((e) => e.status === "reply").length;
  return <>
    <div className={s.summary}><div className={s.summaryIntro}><h2>One plan. Every touch connected.</h2><p className={s.caption}>Research, ownership and the next step for each account.</p></div><div><strong>{data.accounts.length}</strong><span className={s.summaryLabel}>Target accounts · {new Set(data.accounts.map((a) => a.approach)).size} approaches</span></div><div><strong>{drafts}</strong><span className={s.summaryLabel}>Messages to review</span></div><div><strong>{reply}</strong><span className={s.summaryLabel}>Conversation needing a reply</span></div></div>
    <div className={s.toolbar}><div className={`${s.row} ${s.wrap}`}><label className={s.search}><Search size={14} /><input aria-label="Search account plan" placeholder="Search accounts or people" value={search} onChange={(e) => setSearch(e.target.value)} /></label><select className={s.select} aria-label="Filter account owner" value={owner} onChange={(e) => setOwner(e.target.value)}><option value="all">All owners</option>{data.people.filter((p) => p.canSend).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select><select className={s.select} aria-label="Filter approach" value={approach} onChange={(e) => setApproach(e.target.value)}><option value="all">All approaches</option>{["Gift-led", "Email-led", "Opportunity support"].map((a) => <option key={a}>{a}</option>)}</select></div><span className={s.caption}>{accounts.length} accounts</span></div>
    <div className={`${s.tableWrap} ${s.planTable}`}><table className={s.table}><thead><tr><th>Account</th><th>Approach</th><th>Account owner</th><th>Connected work</th><th>Status</th><th>Next step</th></tr></thead><tbody>{accounts.map((a) => {
      const mailer = mail?.mailers.find((m) => m.id === a.mailerId), email = data.emails.find((e) => e.accountId === a.id)!;
      const progress = accountProgress(a, mailer, email.status === "reply");
      const nextHref = email.status === "reply" || !a.mailerId ? `/email?message=${email.id}` : `/direct-mail/${a.mailerId}`;
      return <tr key={a.id}><td><Link className={s.row} href={`${projectHref}?account=${a.id}`}><AccountMark account={a} /><div className={s.accountCell}>{a.name}<p className={s.caption}>{a.contact} · {a.role}</p></div></Link></td><td>{a.approach}<p className={s.caption}>Fit {a.fit} · {a.territory}</p></td><td><span className={s.row}><Avatar person={person(data, a.ownerId)} small />{person(data, a.ownerId).name}</span></td><td><div className={s.row}>{a.mailerId ? <Link aria-label={`Gift for ${a.contact}`} href={`/direct-mail/${a.mailerId}`}><Package size={14} /></Link> : null}<Link aria-label={`Page for ${a.name}`} href={`/artifacts?asset=page-${a.id}`}><FileText size={14} /></Link><Link aria-label={`Email for ${a.contact}`} href={`/email?message=${email.id}`}><MessageSquare size={14} /></Link><span className={s.caption}>{data.artifacts.filter((asset) => asset.accountId === a.id).length} assets</span></div></td><td><Status tone={progress.tone}>{!a.mailerId && email.status === "scheduled" ? "Email approved" : progress.label}</Status></td><td><Link className={s.textLink} href={nextHref}>{!a.mailerId && email.status === "scheduled" ? "View approved email" : progress.next}<ArrowUpRight size={12} /></Link></td></tr>;
    })}</tbody></table>{accounts.length === 0 ? <div className={s.empty}><p>No accounts match these filters.</p><button className={s.textLink} onClick={() => { setSearch(""); setOwner("all"); setApproach("all"); }}>Clear filters</button></div> : null}</div>
    <p className={`${s.caption} ${s.spaced}`}>The project coordinates the overall motion. Each campaign owns a channel; each account keeps its relationship owner.</p>
    <section className={s.section}><h2>Channel programs</h2>{data.campaigns.map((campaign) => <div className={s.activity} key={campaign.id}>{campaign.channel === "Direct Mail" ? <Package size={15} /> : campaign.channel === "Email" ? <MessageSquare size={15} /> : <FileText size={15} />}<div><Link className={s.textLink} href={campaign.channel === "Direct Mail" ? "/direct-mail" : campaign.channel === "Email" ? "/email" : "/artifacts?type=ad"}>{campaign.name}<ArrowUpRight size={12} /></Link><p>{campaign.purpose}</p></div><div className={s.caption}>{campaign.channel} · {person(data, campaign.ownerId).name}</div></div>)}</section>
  </>;
}
