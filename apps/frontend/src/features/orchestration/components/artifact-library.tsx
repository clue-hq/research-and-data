"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select-field";
import { MailerPreview } from "@/features/direct-mail/components/mailer-preview";
import type { DirectMailState } from "@/features/direct-mail/model/direct-mail";
import type { CampaignArtifact, WorkspaceState } from "../model/workspace";
import { artifactVersion } from "../model/artifact-version";
import type { PreviewKind } from "./account-detail";
import s from "./workspace.module.css";

export const kindNames = { page: "Landing page", ad: "LinkedIn ad", note: "Handwritten note" };

export function ProjectArtifacts({ data, mail, open }: {
  data: WorkspaceState; mail: DirectMailState | null; open: (id: string, preview: PreviewKind) => void;
}) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("all");
  const [page, setPage] = useState(1);
  const assets = data.artifacts.filter((asset) => (kind === "all" || kind === asset.kind) && asset.title.toLowerCase().includes(search.trim().toLowerCase()));
  const pages = Math.max(1, Math.ceil(assets.length / 25));
  const currentPage = Math.min(page, pages);
  const visible = assets.slice((currentPage - 1) * 25, currentPage * 25);
  return <div className={s.workspace}>
    <div className={s.toolbar}>
      <label className={s.search}><Search size={15} aria-hidden="true" /><input aria-label="Search project artifacts" placeholder="Search artifacts" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} /></label>
      <SelectField ariaLabel="Artifact type" className={s.select} value={kind} onValueChange={(value) => { setKind(value); setPage(1); }} options={[{ value: "all", label: "All types" }, ...Object.entries(kindNames).map(([value, label]) => ({ value, label }))]} />
    </div>
    <div className={s.tableScroll}><table className={s.table}>
      <caption className={s.srOnly}>Artifacts in this project</caption>
      <thead><tr><th>Artifact</th><th>Account</th><th>Type</th><th>Status</th><th>Version</th></tr></thead>
      <tbody>{visible.map((asset) => {
        const account = data.accounts.find((item) => item.id === asset.accountId)!;
        const mailer = mail?.mailers.find((item) => item.id === asset.mailerId);
        return <tr key={asset.id}>
          <td><button className={s.accountButton} onClick={() => open(asset.accountId, asset.kind)}>{asset.title}</button></td>
          <td><button className={s.textButton} onClick={() => open(account.id, "overview")}>{account.name}</button></td>
          <td>{kindNames[asset.kind]}</td><td className={s.muted}>{asset.kind === "note" && mailer?.approval ? "Approved" : asset.status === "review" ? "Needs review" : asset.status === "approved" ? "Approved" : "Draft"}</td><td className={s.muted}>v{artifactVersion(asset, mail)}</td>
        </tr>;
      })}</tbody>
    </table>{!visible.length ? <div className={s.empty}>No artifacts match these filters.</div> : null}</div>
    <footer className={s.pagination}><span>{assets.length} artifacts</span><div className={s.paginationControls}><Button variant="transparent" size="sm" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>Previous</Button><span className={s.pageNumber}>{currentPage} / {pages}</span><Button variant="transparent" size="sm" disabled={currentPage >= pages} onClick={() => setPage(currentPage + 1)}>Next</Button></div></footer>
  </div>;
}

export function ArtifactPreview({ asset, data, mail }: { asset: CampaignArtifact; data: WorkspaceState; mail: DirectMailState | null }) {
  const account = data.accounts.find((item) => item.id === asset.accountId)!;
  const mailer = mail?.mailers.find((item) => item.id === asset.mailerId);
  const card = mailer?.approval?.card ?? mail?.cards.find((item) => item.id === mailer?.cardId);
  const style = mailer?.approval?.style ?? mail?.styles.find((item) => item.id === mailer?.styleId);
  return <>
    <div className={s.previewMeta}><span>{kindNames[asset.kind]} · v{artifactVersion(asset, mail)}</span><span>{asset.kind === "note" && mailer?.approval ? "Approved" : asset.status === "review" ? "Needs review" : asset.status === "approved" ? "Approved" : "Draft"}</span></div>
    {asset.kind === "page" ? <>
      <div className={s.pagePreview}>
        <header><strong>clue</strong><span>For {account.name}</span></header>
        <div className={s.pageHero}><span className={s.pageEyebrow}>An account brief for {(mailer?.recipient.name ?? account.contact).split(" ")[0]}</span><h2>{asset.headline}</h2><p>{asset.body}</p><span className={s.previewCta}>{asset.cta}</span></div>
        <section><h3>{asset.sectionTitle}</h3><p>{asset.sectionBody}</p></section>
      </div>
      <p className={s.previewFootnote}>Not published. A live destination is needed before this page can be linked from the gift’s QR code.</p>
    </> : asset.kind === "ad" ? <>
      <div className={s.adPreview}><header><strong>Clue</strong><span>Sponsored</span></header><p>{asset.body}</p><div className={s.adCreative}><span>Prepared for {account.name}</span><h2>{asset.headline}</h2><strong>clue</strong></div><footer><span>Account brief</span><span>{asset.cta}</span></footer></div>
      <p className={s.previewFootnote}>{account.audienceSize.toLocaleString()} estimated audience members in this example. Audience eligibility, destination and budget still need verification before launch.</p>
    </> : mailer && card ? <MailerPreview card={card} style={style} note={mailer.approval?.note ?? mailer.note} signature={mailer.approval?.signature ?? mailer.signature} /> : <p className={s.caption}>{mail ? "The connected card is unavailable." : "Loading the connected note…"}</p>}
  </>;
}
