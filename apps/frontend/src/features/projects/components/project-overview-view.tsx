import Link from "next/link";
import { Button } from "@/components/ui/button";
import { SidebarFigmaIcon } from "@/components/shell/sidebar-figma-icon";
import { SidebarConversationStatus } from "@/components/shell/sidebar-conversation-status";
import type { ProjectsScreenController } from "../hooks/use-projects-screen-controller";
import { formatProjectDate } from "../model/project-directory";
import { threadLabel } from "../model/chat-thread";
import { ProjectComposer } from "./project-composer";
import { ProjectIcon } from "./project-icon";
import { ProjectDirectoryMenu } from "./project-directory-menu";
import styles from "./projects-directory.module.css";

export function ProjectOverviewView({ controller: c }: { controller: ProjectsScreenController }) {
  const p = c.project;
  if (!p) return null;
  const chats = c.chats;
  return <>
    <header className={styles.pageHeader}><nav className={styles.breadcrumb} aria-label="Project breadcrumb"><Link href="/projects">Projects</Link><span>/</span><span>{p.title}</span></nav></header>
    <div className={styles.scrollArea}><div className={styles.overviewContent}>
      <div className={styles.overviewHeading}><div><h1>{p.title}</h1>{p.description ? <p>{p.description}</p> : null}</div><div className={styles.headingActions}><Button variant="transparent" size="icon-sm" aria-label={p.pinned ? "Unpin project" : "Pin project"} aria-pressed={p.pinned} disabled={c.busy} onClick={() => c.mutate("pin", p.id)}><SidebarFigmaIcon name="sidebar-pin" /></Button><ProjectDirectoryMenu project={p} controller={c} /></div></div>
      {p.status === "archived" ? <div className={styles.archiveNotice}>Archived project<Button size="sm" variant="secondary" disabled={c.busy} onClick={() => c.mutate("archive", p.id)}>Restore project</Button></div> : null}
      <div className={styles.chatColumns}>
        <section className={styles.chatsMain} aria-label="Project chats">
          {c.shell && c.selectedModel ? <ProjectComposer attachmentError={c.attachmentError} attachments={c.attachments} disabled={c.busy || p.status === "archived"} entities={c.shell.entities} modelPickerOpen={c.modelPickerOpen} models={c.models} onAttachmentFiles={c.shell.composerCapabilities.attachments ? c.addAttachments : undefined} onAttachmentRemove={c.shell.composerCapabilities.attachments ? c.removeAttachment : undefined} onEntityRemove={c.shell.composerCapabilities.contextRefs ? c.removeEntity : undefined} onEntitySelect={c.shell.composerCapabilities.contextRefs ? c.selectEntity : undefined} onModelPickerToggle={c.toggleModelPicker} onModelSelect={c.selectModel} onPromptChange={c.setPrompt} onSubmit={prompt => { void c.newChat(p.id, prompt ?? c.prompt); return true; }} prompt={c.prompt} sendDisabled={c.busy} selectedEntities={c.selectedEntities} selectedEntityIds={c.selectedEntityIds} selectedModel={c.selectedModel} /> : null}
          <h2 className={styles.recentsTitle}>Recent chats</h2>
          <div>{chats.map(chat => <div className={styles.chatRow} key={chat.id}><Link href={chat.href}>{threadLabel(chat)}</Link><div className={styles.chatRowMeta}><SidebarConversationStatus status={chat.status} /><time dateTime={chat.updatedAt}>{formatProjectDate(chat.updatedAt)}</time></div></div>)}</div>
          {!chats.length ? <p className={styles.noChats}>Your conversations will appear here.</p> : null}
        </section>
        <aside className={styles.contextRail} aria-label="Project context">
          <section><div className={styles.railTitle}><h2>Instructions</h2><Button variant="transparent" size="icon-sm" aria-label={c.instructions ? "Edit instructions" : "Add instructions"} disabled={p.status === "archived"} onClick={() => c.openDialog("instructions", p)}><ProjectIcon name={c.instructions ? "edit" : "plus"} size={12} /></Button></div><p>{c.instructions || "Add instructions for this project."}</p></section>
          <section><div className={styles.railTitle}><h2>Memory</h2><Button variant="transparent" size="icon-sm" aria-label="Add memory" disabled={p.status === "archived"} onClick={() => c.openDialog("memory", p)}><ProjectIcon name="plus" size={12} /></Button></div>{c.memory.length ? c.memory.map(entry => <div className={styles.railMemory} key={entry.id}><button className={styles.memoryNoteButton} type="button" disabled={p.status === "archived"} onClick={() => c.openDialog("memory", p, entry.id)}>{entry.text}</button><div className={styles.memorySource}>{entry.sourceThreadId ? <Link href={c.chats.find(chat => chat.id === entry.sourceThreadId)?.href ?? "#"}>{c.chats.find(chat => chat.id === entry.sourceThreadId)?.title ?? entry.sourceThreadTitle ?? "Source chat"}</Link> : <span>Added by you</span>}<span> · {formatProjectDate(entry.createdAt)}</span></div></div>) : <p>No project memory yet.</p>}</section>
        </aside>
      </div>
    </div></div>
  </>;
}
