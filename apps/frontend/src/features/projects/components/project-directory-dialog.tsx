import { Dialog } from "@base-ui/react/dialog";
import { Button } from "@/components/ui/button";
import { threadLabel } from "../model/chat-thread";
import { ProjectIcon } from "./project-icon";
import type { ProjectsScreenController } from "../hooks/use-projects-screen-controller";
import styles from "./projects-directory.module.css";

export function ProjectDirectoryDialog({ controller: c }: { controller: ProjectsScreenController }) {
  const kind = c.dialog?.kind;
  const details = kind === "create" || kind === "details";
  const titles = { create: "Create a project", details: "Edit project details", instructions: "Project instructions", memory: c.dialog?.entryId ? "Edit memory" : "Remember for this project" };
  return <Dialog.Root open={Boolean(c.dialog)} onOpenChange={open => { if (!open) c.closeDialog(); }}>
    <Dialog.Portal><Dialog.Backdrop className={styles.dialogBackdrop} /><Dialog.Popup className={styles.dialog}>
      <form onSubmit={e => { e.preventDefault(); void c.saveDialog(); }}>
        <div className={styles.dialogHeader}><Dialog.Title className={styles.dialogTitle}>{kind ? titles[kind] : "Project"}</Dialog.Title><Button size="icon-sm" variant="transparent" aria-label="Close dialog" disabled={c.busy} onClick={c.closeDialog}><ProjectIcon name="close" size={14} /></Button></div>
        <Dialog.Description className="sr-only">{kind === "create" ? "Enter a project name and an optional goal." : "This context stays with this project."}</Dialog.Description>
        {details ? <><label className={styles.formField}>Project name<input autoFocus required maxLength={120} value={c.name} onChange={e => c.setName(e.target.value)} placeholder="Name your project" /></label><label className={styles.formField}>What are you trying to achieve?<textarea maxLength={2000} value={c.description} onChange={e => c.setDescription(e.target.value)} placeholder="Describe the goal of this project" rows={3} /></label></> : null}
        {kind === "instructions" || kind === "memory" ? <label className={styles.formField}>{kind === "instructions" ? "How should Clue work in this project?" : "What should this project remember?"}<textarea autoFocus required={kind === "memory"} maxLength={kind === "memory" ? 4000 : 12000} rows={6} value={c.text} onChange={e => c.setText(e.target.value)} placeholder={kind === "instructions" ? "Goals, tone, constraints, and preferences…" : "Add a useful decision or fact…"} /></label> : null}
        {kind === "memory" ? <div className={styles.formField}><span>Source chat</span><select aria-label="Memory source chat" value={c.sourceChatId} onChange={e => c.setSourceChatId(e.target.value)}><option value="">Added by you</option>{c.chats.map(chat => <option key={chat.id} value={chat.id}>{threadLabel(chat)}</option>)}</select></div> : null}
        {c.error ? <p className={styles.formError} role="alert">{c.error}</p> : null}
        <div className={styles.dialogActions}>{kind === "memory" && c.dialog?.entryId ? <Button size="md" variant="transparent" className={styles.removeMemory} disabled={c.busy} onClick={() => void c.removeMemory()}>Remove memory</Button> : null}<Button size="md" variant="secondary" disabled={c.busy} onClick={c.closeDialog}>Cancel</Button><Button type="submit" size="md" disabled={c.busy || (details && !c.name.trim()) || (kind === "memory" && !c.text.trim())}>{c.busy ? "Saving…" : kind === "create" ? "Create project" : "Save changes"}</Button></div>
      </form>
    </Dialog.Popup></Dialog.Portal>
  </Dialog.Root>;
}
