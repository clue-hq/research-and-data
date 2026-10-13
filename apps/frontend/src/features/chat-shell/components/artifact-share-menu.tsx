import {
  ArrowLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  ExternalLinkIcon,
  Link2Icon,
  PencilIcon,
  RefreshCwIcon,
  SlidersHorizontalIcon,
  type LucideIcon,
} from "lucide-react";
import type { KeyboardEvent } from "react";
import {
  pageLinkRows,
  type useArtifactSharingController,
} from "../hooks/use-artifact-sharing-controller";
import styles from "./chat-shell.module.css";

const SHARE_MENU_ICONS = {
  "arrow-left": ArrowLeftIcon,
  "chevron-right": ChevronRightIcon,
  copy: CopyIcon,
  "external-link": ExternalLinkIcon,
  link: Link2Icon,
  pencil: PencilIcon,
  refresh: RefreshCwIcon,
  sliders: SlidersHorizontalIcon,
} satisfies Record<string, LucideIcon>;

type ShareMenuIconName = keyof typeof SHARE_MENU_ICONS;

type ShareController = ReturnType<
  typeof useArtifactSharingController
>["controller"];

function ShareMenuIcon({
  name,
  size = 14,
}: {
  name: ShareMenuIconName;
  size?: number;
}) {
  const Icon = SHARE_MENU_ICONS[name];

  return (
    <Icon
      absoluteStrokeWidth
      aria-hidden="true"
      size={size}
      strokeWidth={1.5}
    />
  );
}

function ShareMenuHeader({
  onBack,
  title,
}: {
  onBack: () => void;
  title: string;
}) {
  return (
    <div className={styles.shareMenuSubheader}>
      <button
        aria-label="Back to Share"
        className={styles.shareMenuIconButton}
        onClick={onBack}
        type="button"
      >
        <ShareMenuIcon name="arrow-left" />
      </button>
      <strong>{title}</strong>
      <span aria-hidden="true" className={styles.shareMenuHeaderSpacer} />
    </div>
  );
}

function ShareCheckbox({
  checked,
  description,
  label,
  onChange,
}: {
  checked: boolean;
  description: string;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      aria-checked={checked}
      className={styles.shareCheckboxRow}
      onClick={() => onChange(!checked)}
      role="checkbox"
      type="button"
    >
      <span className={styles.shareCheckboxBox}>
        {checked ? <span className={styles.shareCheckboxMark}>✓</span> : null}
      </span>
      <span>
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
    </button>
  );
}

function ShareMainView({ controller }: { controller: ShareController }) {
  const {
    beginSlugEdit,
    copied,
    copyLink,
    editingSlug,
    previewExternally,
    publishAsset,
    publishStatus,
    saveSlug,
    setSlugDraft,
    setView,
    shareHost,
    slug,
    slugDirty,
    slugDraft,
  } = controller;
  const published = publishStatus === "published";
  const publishing = publishStatus === "publishing";
  // A published site with a pending change (a new slug, new settings) shows the
  // publish button again, reading "Republish" — the live site keeps serving its
  // current address until it is pressed.
  const showingPublishButton = !published || slugDirty;
  const handleSlugKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") saveSlug();
  };

  return (
    <div className={styles.shareMenuSection}>
      <div className={styles.sharePublishHeading}>
        {published ? (
          <>
            <span className={styles.sharePublishedDot} />
            <strong>Asset published</strong>
          </>
        ) : (
          <strong>Publish to share outside your workspace</strong>
        )}
      </div>

      <div className={styles.shareLinkField}>
        <ShareMenuIcon name="link" />
        {shareHost ? (
          <span className={styles.shareLinkHost}>{shareHost}/</span>
        ) : null}
        {editingSlug ? (
          <input
            aria-label="Publishing link path"
            autoFocus
            maxLength={72}
            onChange={(event) => setSlugDraft(event.target.value)}
            onKeyDown={handleSlugKeyDown}
            value={slugDraft}
          />
        ) : (
          <span className={styles.shareLinkSlug}>{slug}</span>
        )}
        <button
          aria-label={editingSlug ? "Save publishing link" : "Edit publishing link"}
          className={styles.shareLinkEditButton}
          onClick={editingSlug ? saveSlug : beginSlugEdit}
          type="button"
        >
          {editingSlug ? "Save" : <ShareMenuIcon name="pencil" size={13} />}
        </button>
      </div>

      {!showingPublishButton ? (
        <div className={styles.sharePublishedActions}>
          <button
            className={styles.shareSecondaryButton}
            onClick={previewExternally}
            type="button"
          >
            <ShareMenuIcon name="external-link" />
            Preview externally
          </button>
          <button
            className={styles.sharePrimaryButton}
            onClick={copyLink}
            type="button"
          >
            <ShareMenuIcon name="copy" />
            {copied ? "Copied" : "Copy link"}
          </button>
        </div>
      ) : (
        <button
          className={styles.sharePrimaryButtonWide}
          disabled={publishing}
          onClick={() => void publishAsset()}
          type="button"
        >
          {publishing
            ? "Publishing…"
            : slugDirty
              ? "Republish"
              : "Publish asset"}
        </button>
      )}

      <div className={styles.shareSettingsList}>
        <button
          className={styles.shareSettingRow}
          onClick={() => setView("advanced")}
          type="button"
        >
          <ShareMenuIcon name="sliders" />
          <span>Advanced publishing settings</span>
          <ShareMenuIcon name="chevron-right" size={12} />
        </button>
      </div>
    </div>
  );
}

function ShareAdvancedView({ controller }: { controller: ShareController }) {
  const {
    advancedTab,
    allowIndexing,
    customHtml,
    description,
    pageUrls,
    regenerateDescriptionOnPublish,
    requestDescriptionGeneration,
    saveAdvancedSettings,
    setAdvancedTab,
    setAllowIndexing,
    setCustomHtml,
    setDescription,
    setRegenerateDescriptionOnPublish,
    setShareTitle,
    setView,
    shareTitle,
  } = controller;
  const pageRows = pageLinkRows(pageUrls);

  return (
    <>
      <ShareMenuHeader
        onBack={() => setView("main")}
        title="Advanced publishing settings"
      />
      <div className={styles.shareMenuSection}>
        <div aria-label="Publishing settings type" className={styles.shareSegmentedControl}>
          <button
            aria-pressed={advancedTab === "page"}
            onClick={() => setAdvancedTab("page")}
            type="button"
          >
            Page settings
          </button>
          <button
            aria-pressed={advancedTab === "html"}
            onClick={() => setAdvancedTab("html")}
            type="button"
          >
            Custom HTML
          </button>
        </div>

        {advancedTab === "page" ? (
          <div className={styles.shareAdvancedFields}>
            <p>Used in search results and link previews when your page is shared.</p>
            <label className={styles.shareField}>
              <span>Title</span>
              <input
                maxLength={60}
                onChange={(event) => setShareTitle(event.target.value)}
                placeholder="Title"
                value={shareTitle}
              />
              <small>{shareTitle.length}/60 characters</small>
            </label>
            <label className={styles.shareField}>
              <span className={styles.shareFieldHeading}>
                <span>Description</span>
                <button onClick={requestDescriptionGeneration} type="button">
                  <ShareMenuIcon name="refresh" size={12} />
                  Generate
                </button>
              </span>
              <textarea
                maxLength={300}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Description"
                rows={4}
                value={description}
              />
              <small>{description.length}/300 characters</small>
            </label>
            <ShareCheckbox
              checked={regenerateDescriptionOnPublish}
              description="Refresh the description and title from the latest page content."
              label="Regenerate description on publish"
              onChange={setRegenerateDescriptionOnPublish}
            />
            <ShareCheckbox
              checked={allowIndexing}
              description="Allow search engines and AI systems to discover this page."
              label="Allow search engine and AI indexing"
              onChange={setAllowIndexing}
            />
            {/* FLAGGED F5 T16: no designed slot for per-page links; minimal neutral list pending founder/design ruling. */}
            {pageRows.length > 1 ? (
              <div className={styles.shareField}>
                <span>Pages</span>
                {pageRows.map((row) => (
                  <small key={row.route}>
                    {row.label}{" "}
                    <a href={row.url} rel="noreferrer" target="_blank">
                      {row.url}
                    </a>
                  </small>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <label className={`${styles.shareField} ${styles.shareCustomHtmlField}`}>
            <span>Custom HTML</span>
            <p>Add markup that the publishing service will place in the page head.</p>
            <textarea
              onChange={(event) => setCustomHtml(event.target.value)}
              placeholder="<!-- Custom HTML -->"
              rows={8}
              value={customHtml}
            />
          </label>
        )}

        <button
          className={styles.sharePrimaryButtonWide}
          onClick={saveAdvancedSettings}
          type="button"
        >
          Save settings
        </button>
      </div>
    </>
  );
}

export function ArtifactShareMenu({ controller }: { controller: ShareController }) {
  return (
    <div aria-label="Share artifact" className={styles.shareMenu} role="dialog">
      {controller.view === "main" ? (
        <ShareMainView controller={controller} />
      ) : null}
      {controller.view === "advanced" ? (
        <ShareAdvancedView controller={controller} />
      ) : null}
      <span aria-live="polite" className={styles.srOnly}>
        {controller.statusMessage}
      </span>
    </div>
  );
}
