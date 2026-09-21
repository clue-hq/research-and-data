import { CheckboxField } from "@/components/ui/checkbox-field";
import { SelectField } from "@/components/ui/select-field";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import type { BrandAsset } from "../model/brand-context";
import { CreativeTypeSchema, UsageRoleSchema, assetLabel, type CreativeType } from "../model/asset-context";
import styles from "./brand-context.module.css";

export function AssetContextDetails({ asset, controller }: { asset: BrandAsset; controller: BrandContextController }) {
  const context = asset.context;
  const library = controller.assetLibrary;
  const interpretations = context?.agent_context?.source_interpretations ?? [];
  const observations = Object.entries(context?.agent_context?.observed ?? {}).filter(([, value]) => Array.isArray(value) ? value.length : value?.trim());
  const analyzing = context && ["queued", "analyzing"].includes(context.status);
  return <>
    <section className={styles.assetGuidance} aria-label="Usage guidance">
      <h3>When to use</h3>
      <p>{context?.usage?.trim() || (analyzing ? "Usage guidance will appear when analysis finishes." : "No usage guidance is available for this asset yet.")}</p>
      {context?.placement?.trim() ? <><h3>Placement & composition</h3><p>{context.placement}</p></> : null}
      {context?.avoid_when?.trim() ? <><h3>When to avoid</h3><p>{context.avoid_when}</p></> : null}
    </section>
    <div className={styles.assetDetailField}>
      <label htmlFor="asset-creative-type">Type</label>
      <SelectField id="asset-creative-type" ariaLabel="Asset type" disabled={!library.canWrite} value={context?.creative_type ?? "unknown"}
        onValueChange={value => controller.setCreativeType(value as CreativeType)}
        options={CreativeTypeSchema.options.map(value => ({value, label: assetLabel(value)}))} />
      <p className={styles.assetFieldHint}>{context?.classification_origin === "human" ? "Chosen by you" : context?.classification_reason || "Analysis has not classified this asset yet."}</p>
    </div>
    <fieldset className={styles.assetUsageField} disabled={!library.canWrite}>
      <legend>Used as</legend>
      <div className={styles.assetRoleOptions}>{UsageRoleSchema.options.map(role => <CheckboxField key={role}
        checked={context?.usage_roles.includes(role) ?? false} onChange={event => {
          const roles = new Set(context?.usage_roles ?? []);
          if (event.target.checked) roles.add(role); else roles.delete(role);
          void library.save(asset.id, {usage_roles: [...roles]});
        }}>{assetLabel(role)}</CheckboxField>)}</div>
    </fieldset>
    <div className={styles.assetDetailField}>
      <label htmlFor="asset-note">Your context</label>
      <textarea id="asset-note" maxLength={4000} readOnly={!library.canWrite} value={context?.user_note ?? ""}
        onChange={event => { if (library.canWrite) library.edits.stage(asset.id, {user_note: event.target.value}); }}
        onBlur={() => void library.edits.flush(asset.id)} placeholder="What should the design agent know?" />
      {library.canWrite ? <p className={styles.assetFieldHint}>Changes save automatically.</p> : null}
    </div>
    <details className={styles.assetContextSection}>
      <summary>Source & reference</summary>
      <div className={styles.assetDisclosureBody}>
        <p>{asset.sources?.map(assetLabel).join(", ") || "Source unknown"}</p>
        {context?.source_occurrences.map(occurrence => <div className={styles.assetSourceOccurrence} key={occurrence.occurrence_id}>
          <p>{occurrence.page_url ?? occurrence.ad_permalink ?? occurrence.advertiser ?? assetLabel(occurrence.source)}</p>
          {occurrence.locator ? <p className={styles.assetFieldHint}>{occurrence.locator}</p> : null}
          {occurrence.headline ? <p>{occurrence.headline}</p> : null}
          {occurrence.commentary ? <p>{occurrence.commentary}</p> : null}
        </div>)}
        {context?.agent_context?.reuse_boundary ? <p>{context.agent_context.reuse_boundary}</p> : null}
      </div>
    </details>
    <details className={styles.assetContextSection}>
      <summary>Agent context</summary>
      <div className={styles.assetDisclosureBody}>
        <p className={styles.assetFieldHint}>{assetLabel(context?.status ?? "stale")} · Revision {context?.revision ?? 0}</p>
        {observations.length ? <dl>{observations.map(([key, value]) => <div key={key}><dt>{assetLabel(key)}</dt><dd>{Array.isArray(value) ? value.join(" · ") : value}</dd></div>)}</dl> : <p>No visual analysis yet.</p>}
        {interpretations.map(item => {
          const fields = [
            ["Call to action", item.cta],
            ["Composition", [item.visual_hierarchy, item.copy_density].filter(Boolean).join(" · ")],
            ["Product hypothesis", item.product_or_use_case_hypothesis],
            ["Audience hypothesis", item.audience_hypothesis],
            ["Design patterns", item.design_patterns.join(" · ")],
            ["Uncertainties", item.uncertainties.join(" · ")],
          ].filter(([, value]) => value.trim());
          if (!fields.length) return null;
          return <section key={item.occurrence_id}><h3>Source interpretation</h3><dl>{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></section>;
        })}
        {context?.agent_context?.uncertainties.length ? <p>{context.agent_context.uncertainties.join(" · ")}</p> : null}
        {context?.diagnostic ? <p role="status">{context.diagnostic.message}</p> : null}
        {library.canWrite && ["stale", "failed", "unsupported"].includes(context?.status ?? "stale") ? <button type="button" className={styles.secondaryButton} onClick={() => library.retry(asset.id)}>Analyze asset</button> : null}
      </div>
    </details>
    {library.canWrite && Object.keys(context?.overrides ?? {}).length ? <details className={styles.assetContextSection}>
      <summary>Your edits</summary>
      <div className={styles.assetDisclosureBody}>
        <p className={styles.assetFieldHint}>Your edits take priority over analysis. Restore a suggestion for individual fields.</p>
        {Object.keys(context!.overrides).map(field => <button key={field} type="button" className={styles.assetResetButton} onClick={() => void library.save(asset.id, {reset_fields: [field]})}>Restore suggested {field === "user_note" ? "context" : assetLabel(field).toLowerCase()}</button>)}
      </div>
    </details> : null}
    {library.error ? <p className={styles.assetSaveError} role="alert">{library.error}</p> : null}
  </>;
}
