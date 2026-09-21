import { useState } from "react";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import type { BrandAsset } from "../model/brand-context";
import { CreativeTypeSchema, UsageRoleSchema, assetLabel, type CreativeType } from "../model/asset-context";
import styles from "./brand-context.module.css";

export function AssetContextDetails({asset, controller}: {asset: BrandAsset; controller: BrandContextController}) {
  const context = asset.context;
  const library = controller.assetLibrary;
  const [note, setNote] = useState<string | null>(null);
  const interpretations = context?.agent_context?.source_interpretations ?? [];
  return <>
    <div className={styles.detailField}>
      <label htmlFor="asset-creative-type">Type</label>
      <select id="asset-creative-type" disabled={library.saving} value={context?.creative_type ?? "unknown"} onChange={event => controller.setCreativeType(event.target.value as CreativeType)}>
        {CreativeTypeSchema.options.map(value => <option key={value} value={value}>{assetLabel(value)}</option>)}
      </select>
      <small>{context?.classification_origin === "human" ? "Chosen by you" : context?.classification_reason ?? "Analysis has not classified this asset yet."}</small>
    </div>
    <fieldset className={styles.detailField} disabled={library.saving}>
      <legend>Used as</legend>
      <div className={styles.assetRoleOptions}>{UsageRoleSchema.options.map(role => <label key={role}>
        <input type="checkbox" checked={context?.usage_roles.includes(role) ?? false} onChange={event => {
          const roles = new Set(context?.usage_roles ?? []);
          if (event.target.checked) roles.add(role); else roles.delete(role);
          void library.save(asset.id, {usage_roles: [...roles]});
        }} />{assetLabel(role)}
      </label>)}</div>
    </fieldset>
    <div className={styles.detailField}>
      <label htmlFor="asset-note">Your context</label>
      <textarea id="asset-note" maxLength={4000} value={note ?? context?.user_note ?? ""} onChange={event => setNote(event.target.value)} placeholder="What should the design agent know?" />
      <button type="button" className={styles.secondaryButton} disabled={note === null || library.saving} onClick={async () => {if (await library.save(asset.id, {user_note: note ?? ""})) setNote(null);}}>Save context</button>
    </div>
    <details open className={styles.assetContextSection}>
      <summary>Reference</summary>
      <p>{context?.usage ?? "Usage guidance is not available yet."}</p>
      {context?.avoid_when ? <p>Avoid when: {context.avoid_when}</p> : null}
      {context?.placement ? <p>Placement: {context.placement}</p> : null}
      <p>Source: {asset.sources?.map(assetLabel).join(", ") || "Unknown"}</p>
      {context?.source_occurrences.map(occurrence => <div key={occurrence.occurrence_id}>
        <p>{occurrence.page_url ?? occurrence.ad_permalink ?? occurrence.advertiser ?? assetLabel(occurrence.source)}</p>
        {occurrence.locator ? <small>{occurrence.locator}</small> : null}
        {occurrence.headline ? <p>{occurrence.headline}</p> : null}
        {occurrence.commentary ? <p>{occurrence.commentary}</p> : null}
      </div>)}
    </details>
    <details className={styles.assetContextSection}>
      <summary>Agent context · revision {context?.revision ?? 0}</summary>
      <p>{assetLabel(context?.status ?? "stale")}</p>
      {context?.agent_context?.observed ? <dl>{Object.entries(context.agent_context.observed).map(([key, value]) => <div key={key}><dt>{assetLabel(key)}</dt><dd>{Array.isArray(value) ? value.join(" · ") : value}</dd></div>)}</dl> : <p>No visual analysis yet.</p>}
      {interpretations.map(item => <div key={item.occurrence_id}>
        <h3>Source interpretation</h3>
        <p>{item.observed_usage}</p>
        <p>Logo relationship: {assetLabel(item.logo_relationship)}. {item.relationship_evidence}</p>
        <p>Messaging: {item.messaging_angle} {item.tone}</p>
        <p>CTA: {item.cta}</p><p>{item.visual_hierarchy} {item.copy_density}</p>
        <p>Product hypothesis: {item.product_or_use_case_hypothesis}</p>
        <p>Audience hypothesis: {item.audience_hypothesis}</p>
        <p>{item.design_patterns.join(" · ")}</p><p>{item.uncertainties.join(" · ")}</p>
      </div>)}
      <p>{context?.agent_context?.reuse_boundary}</p>
      <p>{context?.agent_context?.uncertainties.join(" · ")}</p>
      {context?.diagnostic ? <p role="status">{context.diagnostic.message}</p> : null}
      {["stale", "failed", "unsupported"].includes(context?.status ?? "stale") ? <button type="button" className={styles.secondaryButton} onClick={() => library.retry(asset.id)}>Analyze asset</button> : null}
    </details>
    {Object.keys(context?.overrides ?? {}).length ? <details className={styles.assetContextSection}>
      <summary>Your overrides</summary>
      {Object.keys(context!.overrides).map(field => <button key={field} type="button" className={styles.secondaryButton} disabled={library.saving} onClick={() => library.save(asset.id, {reset_fields: [field]})}>Reset {assetLabel(field)} to suggestion</button>)}
    </details> : null}
    {library.error ? <p role="alert">{library.error}</p> : null}
  </>;
}
