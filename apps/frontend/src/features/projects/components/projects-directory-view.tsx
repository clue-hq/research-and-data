import Link from "next/link";
import { Button } from "@/components/ui/button";
import { AccountFilterSelect } from "@/features/accounts/components/account-filter-select";
import { SidebarFigmaIcon } from "@/components/shell/sidebar-figma-icon";
import { ProjectIcon } from "./project-icon";
import { ProjectDirectoryMenu } from "./project-directory-menu";
import { formatProjectDate, projectHomeHref } from "../model/project-directory";
import type { ProjectsScreenController } from "../hooks/use-projects-screen-controller";
import styles from "./projects-directory.module.css";

export function ProjectsDirectoryView({ controller: c }: { controller: ProjectsScreenController }) {
  return <div className={styles.scrollArea}>
    <div className={styles.directoryContent}>
      <header className={styles.directoryHeader}>
        <h1>{c.filter === "archived" ? "Archived projects" : "Projects"}</h1>
        <div className={styles.directoryActions}>
          {c.searchOpen ? <label className={styles.search}><ProjectIcon name="search" size={14} /><input autoFocus type="search" aria-label="Search projects" placeholder="Search projects" value={c.query} onChange={e => c.setQuery(e.target.value)} /></label> : <Button variant="transparent" size="icon" aria-label="Search projects" onClick={c.showSearch}><ProjectIcon name="search" size={14} /></Button>}
          <div className={styles.selectControl}><AccountFilterSelect ariaLabel="Sort projects" value={c.sort} onValueChange={c.setSort} options={[{ label: "Last updated", value: "updated" }, { label: "Date created", value: "created" }, { label: "Alphabetical", value: "name" }]} /></div>
          <Button size="md" onClick={() => c.openDialog("create")}>New project</Button>
        </div>
      </header>
      <div className={styles.projectGrid}>
        {c.projects.map(p => <article className={styles.projectCard} key={p.id}>
          <div className={styles.cardHeading}>
            <Link className={styles.cardTitle} href={projectHomeHref(p.id)}>{p.title}</Link>
            <div className={styles.cardMenu}><ProjectDirectoryMenu project={p} controller={c} /></div>
          </div>
          {p.description ? <p className={styles.cardDescription}>{p.description}</p> : null}
          <div className={styles.cardFooter}><time dateTime={p.updatedAt}>{formatProjectDate(p.updatedAt)}</time>{p.pinned ? <span aria-label="Pinned project"><SidebarFigmaIcon name="sidebar-pin" size={12} /></span> : null}</div>
        </article>)}
      </div>
      {!c.projects.length ? <div className={styles.empty}><h2>{c.query ? "No projects found" : c.filter === "archived" ? "No archived projects" : "No projects yet"}</h2>{c.query ? <p>Try a different project name.</p> : c.filter !== "archived" ? <Button size="md" variant="secondary" onClick={() => c.openDialog("create")}>Create a project</Button> : null}</div> : null}
      <footer className={styles.directoryFooter}>
        <button type="button" onClick={() => c.setFilter(c.filter === "archived" ? "active" : "archived")}>{c.filter === "archived" ? "Back to projects" : "Archived projects"}</button>
        {c.total > 12 ? <div className={styles.pagination}><span>{c.page} / {Math.ceil(c.total / 12)}</span><Button size="sm" variant="transparent" disabled={c.page === 1} onClick={() => c.setPage(c.page - 1)}>Previous</Button><Button size="sm" variant="transparent" disabled={c.page * 12 >= c.total} onClick={() => c.setPage(c.page + 1)}>Next</Button></div> : null}
      </footer>
    </div>
  </div>;
}
