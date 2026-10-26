"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ChevronRight, ArrowUpRight, SlidersHorizontal } from "lucide-react";
import { ApplicationShell } from "@/components/shell/application-shell";
import { useDirectMail } from "@/features/direct-mail/hooks/use-direct-mail";
import { useWorkspace } from "../hooks/use-workspace";
import { chatHref, person, projectHref, replyAttention } from "../model/workspace";
import { ProjectPlan } from "./project-plan";
import { ProjectConversation } from "./project-conversation";
import { AccountDetail } from "./account-detail";
import { ArtifactLibraryV2, ArtifactDetail } from "./artifact-library";
import { EmailWorkspace } from "./email-workspace";
import { ResultsView } from "./results-view";
import { Avatar } from "./workspace-ui";
import s from "./workspace.module.css";

export type WorkspaceView = "home" | "plan" | "chat" | "artifacts" | "email" | "results";
export function WorkspaceScreen({ view = "plan", projectScoped = false }: { view?: WorkspaceView; projectScoped?: boolean }) {
  const c = useWorkspace(), mail = useDirectMail(), params = useSearchParams(), router = useRouter(), pathname = usePathname();
  const query = (key: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(key,value); else next.delete(key); router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll:false }); };
  const data = c.data;
  const reply = data ? replyAttention(data)[0] : undefined;
  const title = view === "home" ? "Your team’s next steps" : view === "email" ? "Email" : view === "artifacts" ? "Artifacts" : view === "results" ? "Analytics" : data?.project.name ?? "Project";
  const subtitle = view === "home" ? "Prepared work, active conversations and the decisions that need you." : view === "email" ? "Every message connected to an account, a sender and a next step." : view === "artifacts" ? "The pages, messages and creative behind your account plans." : view === "results" ? "Understand what is moving accounts toward a useful conversation." : data?.project.goal;
  const account = data?.accounts.find((a) => a.id === params.get("account")), asset = data?.artifacts.find((a) => a.id === params.get("asset"));
  const insideProject = view === "plan" || view === "chat" || projectScoped;
  const content = <main className={s.screen}><header className={s.topbar}><div className={s.crumb}>{insideProject ? <><Link href="/projects">Projects</Link><ChevronRight size={13} /><span>{data?.project.name ?? "Account plan"}</span></> : <span>{title}</span>}</div><div className={s.row}><span className={s.tag}>V2</span><a className={`${s.caption} ${s.textLink}`} href="http://localhost:5000/direct-mail" target="_blank" rel="noreferrer">Open V1<ArrowUpRight size={12} /></a></div></header><div className={s.body}><div className={s.content}>
    {!c.repository ? <div className={s.empty}><h1 className={s.title}>This experience isn’t connected yet</h1><p className={s.caption}>The connected account experience is available in the isolated V2 preview.</p></div> : <>
      <div className={s.heading}><div><h1 className={s.title}>{title}</h1><p className={s.subtitle}>{subtitle}</p></div>{insideProject ? <Link href="/direct-mail/settings" className={`${s.textLink} text-[12px]`}><SlidersHorizontal size={13} />Project guidance</Link> : <Link className={`${s.textLink} text-[12px]`} href={projectHref}>Open account plan<ArrowUpRight size={12} /></Link>}</div>
      {insideProject && data ? <><div className={s.metadata}><span><Avatar small person={person(data, data.project.ownerId)} />{person(data, data.project.ownerId).name} · Project owner</span><span>{data.accounts.length} target accounts</span><span>{mail.data?.giftBudgets?.[0] ? `$${mail.data.giftBudgets[0].minimumCents/100}–${mail.data.giftBudgets[0].preferredCents/100} preferred · $${mail.data.giftBudgets[0].ceilingCents/100} gift ceiling` : data.project.budget}</span></div><nav className={s.tabs} aria-label="Project views">{[{ label:"Chat", view:"chat", href:chatHref },{ label:"Account plan", view:"plan", href:projectHref },{ label:"Gallery", view:"artifacts", href:`${projectHref}?view=artifacts` },{ label:"Results", view:"results", href:`${projectHref}?view=results` }].map((tab) => <Link key={tab.view} href={tab.href} aria-current={view === tab.view ? "page" : undefined}>{tab.label}</Link>)}</nav></> : null}
      {c.error ? <div className={s.error} role="alert">{c.error} <button className={s.textLink} onClick={() => void c.reload()}>Reload</button></div> : null}
      {mail.error ? <div className={s.error} role="alert">Gift data: {mail.error} <button className={s.textLink} onClick={() => void mail.reload()}>Retry</button></div> : null}
      {!data ? <div className={s.empty} role="status">{c.error ? "The account plan is unavailable." : "Loading the account plan…"}</div> : <>
        {view === "home" ? <div className={`${s.grid2} mb-7`}><Link className={s.card} href={chatHref}><p className={s.eyebrow}>Continue the project</p><h2 className={s.sectionTitle}>{data.project.name} ↗</h2><p className={s.caption}>Research and prepared work for six account conversations.</p></Link><Link className={s.card} href={reply ? `/email?message=${reply.emailId}` : "/email"}><p className={s.eyebrow}>Sales handoff</p><h2 className={s.sectionTitle}>{reply?.title ?? "Review prepared emails"} ↗</h2><p className={s.caption}>{reply?.detail ?? "No outstanding recipient replies. Review the next messages with their senders."}</p></Link></div> : null}
        {view === "plan" || view === "home" ? <ProjectPlan data={data} mail={mail.data} /> : view === "chat" ? <ProjectConversation controller={c} mail={mail.data} /> : view === "artifacts" ? <ArtifactLibraryV2 key={params.get("type") ?? "all"} data={data} mail={mail.data} initialType={params.get("type") ?? undefined} open={(id) => query("asset",id)} /> : view === "email" ? <EmailWorkspace controller={c} messageId={params.get("message") ?? undefined} select={(id) => query("message",id)} /> : <ResultsView data={data} mail={mail.data} />}
        {account ? <AccountDetail account={account} controller={c} mail={mail.data} close={() => query("account","")} /> : params.has("account") ? <div className={s.error} role="alert">Account not found. <button onClick={() => query("account","")}>Close</button></div> : null}
        {asset ? <ArtifactDetail asset={asset} data={data} mail={mail.data} close={() => query("asset","")} /> : params.has("asset") ? <div className={s.error} role="alert">Artifact not found. <button onClick={() => query("asset","")}>Close</button></div> : null}
      </>}
    </>}
  </div></div></main>;
  return insideProject || view === "home" ? content : <ApplicationShell activeHref={view === "results" ? "/analytics" : `/${view}`}>{content}</ApplicationShell>;
}
