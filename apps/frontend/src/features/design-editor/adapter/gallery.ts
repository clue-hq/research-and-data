import {
  ProjectArtifactSchema,
  type ProjectArtifact,
} from "@/features/projects/model/project-workspace";
import type { DesignArtifactListItem } from "../model/artifact";

/**
 * Slice 2: the pure mapper from one listed design artifact (the project's
 * leg-derived design-artifact feed) to the gallery's `ProjectArtifact`.
 *
 * Everything it writes is real: the artifact id, the document's title, its
 * backend timestamps, the origin thread the design leg came from, and (since
 * the 2026-08-31 ruling) the document's own rendered thumbnail. The fields a
 * real document cannot answer are left ABSENT rather than invented —
 * `originRunId` (a leg-derived document has no generation run) is optional in
 * the model for exactly that reason. Ruling 2's "real documents have no
 * thumbnails" no longer holds: they have real ones now, and the card's empty
 * frame is the FALLBACK for a thumbnail that is missing or fails to load,
 * not the universal state.
 *
 * Size and last-viewed are likewise unanswerable here; the gallery's own
 * `normalizeGalleryArtifact` supplies its defaults for them. The ACCOUNT is
 * no longer among them: a multi-artifact design leg births one document per
 * target account, and the feed now says which — so the card states the real
 * account, and a document made for none still says nothing.
 *
 * AD2.1 made it kind-aware. A `web` document is a `website` artifact whose
 * gallery collateral is a `microsite`; an `ad` (scene) document is a `canvas`
 * artifact with `collateralType` ABSENT — the document knows it is an ad, never
 * which channel, so guessing "linkedin-ad" here would paint fabricated
 * vocabulary onto a real artifact. The mapping is also what carries the ad into
 * the editor unchanged: both mounts reconstruct the kind as
 * `source.type === "website" ? "web" : "ad"`, so `canvas` yields `"ad"`.
 */
/** G-H: the document's recorded artifact type → the gallery's own channel
 * vocabulary, and ONLY when it genuinely names one. An unrecognised or absent
 * type maps to nothing: the founder's ruling is that we are not necessarily
 * always making ads, so a card that cannot prove its channel claims none. */
export function collateralTypeFor(artifactType: string | undefined) {
  if (!artifactType) return undefined;
  const value = artifactType.toLowerCase();
  if (value.includes("linkedin")) return "linkedin-ad" as const;
  if (value.includes("meta") || value.includes("facebook") || value.includes("instagram")) {
    return "meta-ad" as const;
  }
  if (value.includes("direct_mail") || value.includes("direct-mail")) {
    return "direct-mail" as const;
  }
  return undefined;
}

/** G-H: the document's real page size → the card's size cell and its
 * size-category filter. Absent when the document has no page; never a default. */
export function sizeFor(widthPx: number | undefined, heightPx: number | undefined) {
  if (!widthPx || !heightPx) return undefined;
  const ratio = widthPx / heightPx;
  const category =
    ratio > 1.05 ? ("landscape" as const) : ratio < 0.95 ? ("portrait" as const) : ("square" as const);
  return { category, height: heightPx, label: `${widthPx} × ${heightPx}`, width: widthPx };
}

/**
 * The card's preview artwork (2026-08-31 ruling): the design API's lazy,
 * version-cached PNG, addressed through the BFF. The version in the URL is
 * the cache key — an edit bumps `currentVersionId`, the URL changes, and the
 * card picks up the fresh thumbnail on its next mount. The empty-frame
 * fallback (ruling 2) remains for a thumbnail that fails to load.
 */
function designThumbnailPath(item: DesignArtifactListItem): string {
  return `/api/clue/design/documents/${encodeURIComponent(item.documentId)}/thumbnail?v=${encodeURIComponent(item.currentVersionId)}`;
}

/** The tag a composer sends pins a numeric design version; anything else is no version. */
function versionOf(currentVersionId: string): number | undefined {
  const value = Number(currentVersionId);
  return Number.isInteger(value) && value > 0 ? value : undefined;
}

export function toProjectArtifact(
  item: DesignArtifactListItem,
  { now = new Date() }: { now?: Date } = {},
): ProjectArtifact {
  const ad = item.kind === "ad";
  const collateralType = ad ? collateralTypeFor(item.artifactType) : "microsite";
  const size = ad ? sizeFor(item.widthPx, item.heightPx) : undefined;
  const version = versionOf(item.currentVersionId);
  const account = item.account;
  return ProjectArtifactSchema.parse({
    ...(collateralType ? { collateralType } : {}),
    ...(size ? { size } : {}),
    // The account the document was made for, onto the three fields the
    // designed card already reads. The logo is Brandfetch's Logo API mark when
    // the backend could build one (founder, 2026-09-20 — the accounts screens'
    // own rule), else the favicon proxy the artifact library uses; an account
    // with no domain names itself and claims no logo.
    ...(account ? { accountId: account.id, accountName: account.name } : {}),
    ...(account?.logoPath
      ? { accountLogoPath: account.logoPath }
      : account?.domain
        ? { accountLogoPath: `/api/source-favicon?domain=${encodeURIComponent(account.domain)}` }
        : {}),
    createdAt: utcInstant(item.createdAt),
    documentId: item.documentId,
    documentKind: item.kind,
    ...(version ? { version } : {}),
    editedLabel: editedLabelFor(item.updatedAt, now),
    id: item.id,
    imagePath: designThumbnailPath(item),
    originThreadId: item.originThreadId,
    title: item.title,
    type: ad ? "canvas" : "website",
    updatedAt: utcInstant(item.updatedAt),
  });
}

/**
 * The backend serializes Postgres timestamptz with an offset
 * (`…T09:15:00+00:00`); the gallery model guards its timestamps with
 * `z.string().datetime()`, which accepts only the Z form. Same instant,
 * canonical spelling.
 */
function utcInstant(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    throw new TypeError(`design artifact timestamp is not a date: ${timestamp}`);
  }
  return parsed.toISOString();
}

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * The gallery's edited label ("Last edited today" — the dummy's style) derived
 * from a real `updated_at`.
 *
 * Today/yesterday are calendar days in the viewer's own zone (a 1am edit reads
 * as today, not as "5 hours ago"); coarser ages fall back to elapsed days. An
 * `updatedAt` ahead of `now` (clock skew) reads as today rather than as a
 * negative age.
 */
export function editedLabelFor(updatedAt: string, now: Date): string {
  const updated = new Date(updatedAt);
  if (Number.isNaN(updated.getTime())) {
    // Same refusal as `utcInstant`, so the two entry points agree on bad
    // input (a silent NaN here once rendered "Last edited NaN years ago").
    throw new TypeError(`design artifact timestamp is not a date: ${updatedAt}`);
  }
  const days = calendarDaysBetween(updated, now);
  if (days <= 0) return "Last edited today";
  if (days === 1) return "Last edited yesterday";
  if (days < 7) return `Last edited ${days} days ago`;
  if (days < 30) return relativeLabel(Math.floor(days / 7), "week");
  if (days < 365) return relativeLabel(Math.floor(days / 30), "month");
  return relativeLabel(Math.floor(days / 365), "year");
}

function relativeLabel(count: number, unit: string): string {
  return `Last edited ${count} ${unit}${count === 1 ? "" : "s"} ago`;
}

function calendarDaysBetween(earlier: Date, later: Date): number {
  return Math.round((startOfDay(later) - startOfDay(earlier)) / DAY_MS);
}

function startOfDay(moment: Date): number {
  return new Date(
    moment.getFullYear(),
    moment.getMonth(),
    moment.getDate(),
  ).getTime();
}
