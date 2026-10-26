"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useDirectMail } from "@/features/direct-mail/hooks/use-direct-mail";
import { useWorkspace } from "../hooks/use-workspace";
import { chatHref, person } from "../model/workspace";
import { ProjectPlan } from "./project-plan";
import { AccountDetail, type PreviewKind } from "./account-detail";
import { ProjectArtifacts } from "./artifact-library";
import s from "./workspace.module.css";

export function WorkspaceScreen() {
  const controller = useWorkspace();
  const mail = useDirectMail();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const data = controller.data;
  const view = params.get("view") === "artifacts" ? "artifacts" : "accounts";
  const account = data?.accounts.find((item) => item.id === params.get("account"));
  const preview = params.get("preview") ?? "overview";
  const updateQuery = (values: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
  };
  const open = (id: string, kind: PreviewKind = "overview") => updateQuery({ account: id, preview: kind });

  return (
    <main className={s.screen}>
      <header className={s.topbar}>
        <Link href="/projects">Projects</Link>
        <span className={s.separator}>/</span>
        <span>{data?.project.name ?? "Project"}</span>
      </header>
      <div className={s.projectHeader}>
        <div>
          <h1 className={s.title}>{data?.project.name ?? "Project"}</h1>
          {data ? <p className={s.caption}>Project owner: {person(data, data.project.ownerId).name}</p> : null}
        </div>
        <Link href="/direct-mail/settings" className={s.quietButton}>Gift settings</Link>
      </div>
      <nav className={s.tabs} aria-label="Project views">
        <button aria-current={view === "accounts" ? "page" : undefined} onClick={() => updateQuery({ view: "", account: "", preview: "" })}>
          Accounts {data ? <span>{data.accounts.length.toLocaleString()}</span> : null}
        </button>
        <button aria-current={view === "artifacts" ? "page" : undefined} onClick={() => updateQuery({ view: "artifacts", account: "", preview: "" })}>
          Artifacts {data ? <span>{data.artifacts.length}</span> : null}
        </button>
        <Link href={chatHref}>Chat</Link>
      </nav>
      {controller.error ? <div className={s.error} role="alert">{controller.error} <button onClick={() => void controller.reload()}>Reload</button></div> : null}
      {mail.error ? <div className={s.error} role="alert">Gift data could not be loaded. <button onClick={() => void mail.reload()}>Retry</button></div> : null}
      {!controller.repository ? <div className={s.empty}>This project preview is available in the local V2 environment.</div>
        : !data ? <div className={s.empty} role="status">{controller.error ? "Project unavailable." : "Loading project…"}</div>
          : view === "accounts" ? <ProjectPlan controller={controller} mail={mail.data} open={open} />
            : <ProjectArtifacts data={data} mail={mail.data} open={open} />}
      {account ? <AccountDetail account={account} controller={controller} mail={mail.data} preview={preview} select={(kind) => open(account.id, kind)} close={() => updateQuery({ account: "", preview: "" })} /> : null}
      {data && params.has("account") && !account ? <div className={s.error} role="alert">Account not found. <button onClick={() => updateQuery({ account: "", preview: "" })}>Dismiss</button></div> : null}
    </main>
  );
}
