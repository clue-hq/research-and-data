"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowUp, ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { WorkspaceController } from "../hooks/use-workspace";
import type { DirectMailState } from "@/features/direct-mail/model/direct-mail";
import { projectHref } from "../model/workspace";
import { accountProgress, AccountMark, Status } from "./workspace-ui";
import s from "./workspace.module.css";

export function ProjectConversation({ controller: c, mail }: { controller: WorkspaceController; mail: DirectMailState | null }) {
  const [input, setInput] = useState("");
  const data = c.data!;
  async function submit(text: string) { if (await c.run(() => c.repository!.addChatMessage(text))) setInput(""); }
  return <div className={s.conversation}>
    {data.messages.map((message) => <div key={message.id} className={message.role === "user" ? s.messageUser : s.message}>{message.role === "assistant" ? <div className={s.agentLabel}><span className={s.accountMark}>C</span>Clue<span className={s.caption}>Account planning</span></div> : null}<p className={s.messageText}>{message.text}</p>{message.id === "proposal" ? <div className={s.prepared}><div className={s.preparedHeader}><span>Prepared account plan</span><Link href={projectHref} className={s.textLink}>View all accounts<ArrowUpRight size={12} /></Link></div>{data.accounts.slice(0,4).map((a) => { const progress = accountProgress(a, mail?.mailers.find((m) => m.id === a.mailerId), data.emails.some((e) => e.accountId === a.id && e.status === "reply")); return <Link className={s.preparedRow} key={a.id} href={`${projectHref}?account=${a.id}`}><span className={s.row}><AccountMark account={a} /><span>{a.name}<span className={`${s.caption} block`}>{a.contact} · {a.approach}</span></span></span><Status tone={progress.tone}>{progress.label}</Status></Link>; })}</div> : null}{message.action !== "none" ? <Link className={`${s.textLink} mt-3 text-[13px]`} href={message.action === "email" ? "/email" : message.action === "review" ? "/direct-mail/mailer-avery" : projectHref}>{message.action === "email" ? "Open email workspace" : message.action === "review" ? "Review Avery’s mailer" : "Open account plan"}<ArrowUpRight size={13} /></Link> : null}</div>)}
    <div className={s.chips}>{["Show gifts ready for review", "Who needs a reply?", "Explain the account approaches"].map((text) => <button className={s.chip} key={text} disabled={c.pending} onClick={() => void submit(text)}>{text}</button>)}</div>
    <form className={s.composer} onSubmit={(e) => { e.preventDefault(); void submit(input); }}><textarea aria-label="Message Clue about this plan" maxLength={2000} placeholder="Ask about the account plan…" value={input} onChange={(e) => setInput(e.target.value)} /><div className={s.composerFooter}><span className={s.caption}>6 accounts · Research and campaign context attached</span><Button type="submit" variant="primary" size="icon-sm" aria-label="Send message" disabled={c.pending || !input.trim()}><ArrowUp size={15} /></Button></div></form><p className={`${s.caption} text-center`}>Local example conversation · No live research or external actions</p>
  </div>;
}
