"use client";

import Image from "next/image";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select-field";
import { estimate, money, selectedGift, stageLabels, type DirectMailState } from "@/features/direct-mail/model/direct-mail";
import type { WorkspaceController } from "../hooks/use-workspace";
import { person, type AccountPlan, type CampaignArtifact } from "../model/workspace";
import { ArtifactPreview, kindNames } from "./artifact-library";
import { DetailPanel } from "./workspace-ui";
import s from "./workspace.module.css";

export type PreviewKind = "overview" | "gift" | CampaignArtifact["kind"];

export function AccountDetail({ account, controller, mail, preview, select, close }: {
  account: AccountPlan;
  controller: WorkspaceController;
  mail: DirectMailState | null;
  preview: string;
  select: (kind: PreviewKind) => void;
  close: () => void;
}) {
  const data = controller.data!;
  const assets = data.artifacts.filter((asset) => asset.accountId === account.id);
  const mailer = mail?.mailers.find((item) => item.id === account.mailerId);
  const gift = mailer ? mailer.approval?.gift ?? selectedGift(mailer) : null;
  const tabs: { id: PreviewKind; label: string }[] = [
    { id: "overview", label: "Overview" },
    ...(account.mailerId ? [{ id: "gift" as const, label: "Gift" }] : []),
    ...assets.map((asset) => ({ id: asset.kind, label: { page: "Page", note: "Note", ad: "Ad" }[asset.kind] })),
  ];
  const active = tabs.some((tab) => tab.id === preview) ? preview : "overview";
  const asset = assets.find((item) => item.kind === active);
  const reviewLabel = mailer?.approval ? "View delivery tracking" : "Review gift, note and cost";

  return <DetailPanel title={account.name} description={account.industry} close={close}>
    <nav className={`${s.tabs} ${s.previewTabs}`} aria-label="Account preview">
      {tabs.map((tab) => <button key={tab.id} aria-current={active === tab.id ? "page" : undefined} onClick={() => select(tab.id)}>{tab.label}</button>)}
    </nav>
    <div className={s.drawerBody}>
      {controller.error ? <div className={s.error} role="alert">{controller.error}</div> : null}
      {active === "overview" ? <>
        <section className={s.section}>
          <div className={s.ownership}>
            <div><label className={s.fieldLabel} htmlFor="account-owner">Account owner</label><SelectField id="account-owner" ariaLabel="Account owner" value={account.ownerId} disabled={controller.pending} options={data.people.filter((p) => p.canOwn).map((p) => ({ value: p.id, label: p.name }))} onValueChange={(ownerId) => void controller.run(() => controller.repository!.assignOwners([{ id: account.id, revision: account.revision }], ownerId))} /></div>
            <div><p className={s.fieldLabel}>Territory</p><p>{account.territory}</p></div>
          </div>
        </section>
        <section className={s.section}>
          <h2>Research</h2>
          {account.researchStatus === "ready" ? <>
            <h3>{account.insight}</h3>
            <p className={s.prose}>{account.evidence}</p>
            <p className={s.source}>{account.source} · {account.observedAt}</p>
          </> : <p className={s.caption}>Research has not started for this account. Contacts and campaign materials will appear here when they are ready.</p>}
        </section>
        {account.contact ? <section className={s.section}>
          <h2>Primary contact</h2>
          <p>{account.contact}</p><p className={s.caption}>{account.role}</p>
          <p className={s.sender}>Sending as {person(data, account.senderId).name}</p>
        </section> : null}
        {gift ? <section className={s.section}>
          <h2>Direct mail</h2>
          <button className={s.giftSummary} onClick={() => select("gift")}>
            <Image src={gift.image} alt={gift.name} width={72} height={72} unoptimized />
            <span><strong>{gift.name}</strong><span className={s.caption}>{mailer ? stageLabels[mailer.stage] : ""}</span></span>
            <span>{money(gift.priceCents)}</span>
          </button>
        </section> : null}
        {assets.length ? <section className={s.section}>
          <h2>Artifacts</h2>
          <div className={s.assetRows}>{assets.map((item) => <button key={item.id} onClick={() => select(item.kind)}>
            <span>{kindNames[item.kind]}</span><span className={s.caption}>{item.kind === "note" && mailer?.approval ? "Approved" : "Draft"}</span>
          </button>)}</div>
        </section> : null}
      </> : active === "gift" ? mailer && gift ? <>
        <div className={s.giftImage}><Image src={gift.image} alt={gift.name} width={360} height={260} unoptimized /></div>
        <div className={s.previewHeading}><div><h2>{gift.name}</h2><p className={s.caption}>{gift.variant} · {gift.merchant}</p></div><span>{money(gift.priceCents)}</span></div>
        <section className={s.section}><h2>Why this gift</h2><p className={s.prose}>{gift.rationale}</p></section>
        <dl className={s.details}>
          <div><dt>Recipient</dt><dd>{account.contact}</dd></div>
          <div><dt>Sender</dt><dd>{mailer.approval?.signature.split("\n")[0] ?? mailer.signature.split("\n")[0]}</dd></div>
          <div><dt>Status</dt><dd>{!mailer.approval && !mailer.addressConfirmed ? "Address needed" : stageLabels[mailer.stage]}</dd></div>
          <div><dt>{mailer.approval ? "Approved cost" : "Estimated total"}</dt><dd>{money(mailer.approval?.estimatedCents ?? estimate(mailer))}</dd></div>
        </dl>
        <p className={s.caption}>Includes the gift, card, packaging and delivery. Review the full breakdown before approving.</p>
      </> : <p className={s.caption}>{mail ? "Gift details are unavailable." : "Loading gift…"}</p>
        : asset ? <ArtifactPreview asset={asset} data={data} mail={mail} /> : null}
    </div>
    {mailer ? <footer className={s.drawerFooter}>
      <Link className={`${buttonVariants({ variant: "primary", size: "md" })} ${s.primaryLink}`} href={`/direct-mail/${mailer.id}`}>{reviewLabel}</Link>
      <span className={s.caption}>{mailer.approval ? stageLabels[mailer.stage] : "Approval required before ordering"}</span>
    </footer> : null}
  </DetailPanel>;
}
