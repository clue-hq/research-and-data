"use client";
import motion from "./account-motion.module.css";

import Image from "next/image";
import { useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { FileText, FolderOpen, Globe, Image as ImageIcon, Mail, Presentation, X } from "lucide-react";
import { DesignIcon } from "@/components/ui/design-icon";
import { useAccountArtifactsController } from "../hooks/use-account-artifacts-controller";
import type { AccountDetail } from "../model/account-detail";
import type { AccountArtifact, AccountWorkspace } from "../model/account-workspace";
import { artifactDisplayType, artifactTypeLabels, artifactTypeOptions, filterAccountActivity, formatAccountDate } from "../model/account-workspace-presentation";
import { AccountWorkspaceShell } from "./account-workspace-shell";
import { AccountFilterSelect } from "./account-filter-select";
import { AccountActivityFeed } from "./account-activity-feed";
import components from "./account-components.module.css";
import research from "./account-research.module.css";
import styles from "./account-library.module.css";

type ScreenProps = { account: AccountDetail; workspace: AccountWorkspace };

const typeIcons = { ad: ImageIcon, web: Globe, document: FileText, presentation: Presentation, email: Mail };
const sortOptions = [
  { value: "recent", label: "Last updated" },
  { value: "name", label: "Name A–Z" },
  { value: "type", label: "Type" },
];

function ArtifactTypeIcon({ type }: { type: AccountArtifact["type"] }) {
  const shown = artifactDisplayType(type);
  const Icon = typeIcons[shown];
  return <span className={styles.typeIcon} data-type={shown}><Icon aria-hidden="true" size={16} strokeWidth={1.5} /></span>;
}

function ArtifactUpdated({ artifact }: { artifact: AccountArtifact }) {
  return artifact.updatedAt
    ? <time dateTime={artifact.updatedAt}>{formatAccountDate(artifact.updatedAt)}</time>
    : <span>{artifact.lastEditedLabel.replace(/^Last edited\s+/i, "")}</span>;
}

export function AccountArtifactsScreen({ account, workspace }: ScreenProps) {
  const controller = useAccountArtifactsController(workspace.accountId === account.id ? workspace.artifacts : [], account.id);
  const [viewMode, setViewMode] = useState<"grid" | "list">("list");

  return (
    <AccountWorkspaceShell account={account} activeTab="artifacts">
      <div className={`${motion.pageEntry} ${research.documentPage}`}>
        <section className={styles.libraryCanvas}>
          <header>
            <h1 className={research.pageTitle}>Artifacts</h1>
            <p className={styles.caption}>Ads, landing pages, and other work for {account.name}.</p>
          </header>

          <div className={styles.toolbar}>
            <label className={styles.search}>
              <DesignIcon name="search" size={14} />
              <span className="sr-only">Search artifacts</span>
              <input onChange={(event) => controller.setSearch(event.target.value)} placeholder="Search artifacts" value={controller.search} />
            </label>
            <div className={styles.typeFilter}>
              <AccountFilterSelect ariaLabel="Filter artifacts by type" onValueChange={controller.setType} options={artifactTypeOptions} value={controller.type} />
            </div>
            <div className={styles.sortFilter}>
              <AccountFilterSelect ariaLabel="Sort artifacts" onValueChange={controller.setSort} options={sortOptions} value={controller.sort} />
            </div>
            <div aria-label="Artifact view" className={`${components.segmentedControl} ${styles.viewControl}`} role="group">
              {(["list", "grid"] as const).map((mode) => (
                <button aria-label={`${mode === "list" ? "List" : "Grid"} view`} aria-pressed={viewMode === mode} className={`${components.segmentedItem} ${viewMode === mode ? components.segmentedItemActive : ""}`} key={mode} onClick={() => setViewMode(mode)} type="button">
                  <DesignIcon name={mode === "list" ? "projects/list" : "projects/gallery"} size={14} />
                </button>
              ))}
            </div>
          </div>

          <p aria-live="polite" className={styles.resultCount}>
            {controller.visibleArtifacts.length === controller.total ? `${controller.total} ${controller.total === 1 ? "artifact" : "artifacts"}` : `${controller.visibleArtifacts.length} of ${controller.total} artifacts`}
          </p>

          {!controller.visibleArtifacts.length ? (
            <div className={styles.emptyState}>
              <FolderOpen aria-hidden="true" size={24} strokeWidth={1.3} />
              <h2>{controller.total ? "No matching artifacts" : "No artifacts yet"}</h2>
              <p>{controller.total ? "Try a different search or type." : `Work generated for ${account.name} will appear here.`}</p>
              {controller.total ? <button className={styles.textButton} onClick={controller.clearFilters} type="button">Clear filters</button> : null}
            </div>
          ) : viewMode === "list" ? (
            <div className={styles.tableWrap}>
              <table className={styles.artifactTable}>
                <thead><tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Updated</th></tr></thead>
                <tbody>{controller.visibleArtifacts.map((artifact) => (
                  <tr key={artifact.id}>
                    <td><button aria-label={`Preview ${artifact.title}`} className={styles.artifactName} onClick={() => controller.openArtifact(artifact)} type="button">
                      <ArtifactTypeIcon type={artifact.type} />
                      <span className={styles.nameText}><span>{artifact.title}</span>{artifact.projectName ? <small>{artifact.projectName}</small> : null}</span>
                    </button></td>
                    <td className={styles.muted}>{artifactTypeLabels[artifact.type]}</td>
                    <td className={styles.muted}><ArtifactUpdated artifact={artifact} /></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : (
            <div className={styles.artifactGrid}>{controller.visibleArtifacts.map((artifact) => (
              <button aria-label={`Preview ${artifact.title}`} className={styles.artifactCard} key={artifact.id} onClick={() => controller.openArtifact(artifact)} type="button">
                {/* unoptimized, as in the gallery: the design thumbnail route is session-authenticated
                    behind the BFF, and the image optimizer's server-side refetch would 401. */}
                <div className={styles.thumbnail}><Image alt="" className="object-cover" fill sizes="(max-width: 640px) 80vw, 300px" src={artifact.thumbnailPath} unoptimized /></div>
                <div className={styles.cardBody}>
                  <div className={styles.cardTitle}><ArtifactTypeIcon type={artifact.type} /><span className={styles.nameText}><span>{artifact.title}</span>{artifact.projectName ? <small>{artifact.projectName}</small> : null}</span></div>
                  <p>{artifactTypeLabels[artifact.type]}<span aria-hidden="true"> · </span><ArtifactUpdated artifact={artifact} /></p>
                </div>
              </button>
            ))}</div>
          )}
        </section>
      </div>

      <Dialog.Root
        onOpenChange={(open) => { if (!open) controller.closeArtifact(); }}
        onOpenChangeComplete={(open) => { if (!open) controller.clearClosedArtifact(); }}
        open={controller.artifactOpen}
      >
        <Dialog.Portal>
          <Dialog.Backdrop className={styles.previewBackdrop} />
          <Dialog.Popup className={styles.previewPopup}>
            {controller.selectedArtifact ? <>
              <header className={styles.previewHeader}>
                <div><Dialog.Title className={styles.previewTitle}>{controller.selectedArtifact.title}</Dialog.Title><Dialog.Description className={styles.caption}>{artifactTypeLabels[controller.selectedArtifact.type]} · {account.name}</Dialog.Description></div>
                <Dialog.Close aria-label="Close artifact preview" className={components.iconButton}><X aria-hidden="true" size={16} strokeWidth={1.5} /></Dialog.Close>
              </header>
              <div className={styles.previewImage}><Image alt={`${controller.selectedArtifact.title} preview`} className="object-contain" fill sizes="90vw" src={controller.selectedArtifact.thumbnailPath} unoptimized /></div>
            </> : null}
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
    </AccountWorkspaceShell>
  );
}

const actorOptions = [{ value: "all", label: "All activity" }, { value: "clue", label: "Clue" }, { value: "person", label: "People" }];

export function AccountActivityScreen({ account, workspace }: ScreenProps) {
  const [actor, setActor] = useState("all");
  const items = filterAccountActivity(workspace.accountId === account.id ? workspace.activity : [], actor);

  return (
    <AccountWorkspaceShell account={account} activeTab="activity">
      <div className={`${motion.pageEntry} ${research.documentPage}`}>
        <section className={research.insightsCanvas}>
          <header className={styles.activityHeader}>
            <h1 className={research.pageTitle}>Activity</h1>
            <div aria-label="Filter activity by actor" className={`${components.segmentedControl} ${styles.actorFilter}`} role="group">
              {actorOptions.map((option) => (
                <button
                  aria-pressed={actor === option.value}
                  className={`${components.segmentedItem} ${styles.actorOption} ${actor === option.value ? components.segmentedItemActive : ""}`}
                  key={option.value}
                  onClick={() => setActor(option.value)}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </header>
          {items.length ? <AccountActivityFeed items={items} /> : <div className={styles.activityEmpty} role="status">{actor === "person" ? "No activity from people yet." : actor === "clue" ? "No Clue activity yet." : "No activity yet."}</div>}
        </section>
      </div>
    </AccountWorkspaceShell>
  );
}
