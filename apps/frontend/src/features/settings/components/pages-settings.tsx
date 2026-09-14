import { Upload } from "lucide-react";
import type { StaticSettings } from "../model/settings";
import styles from "./settings.module.css";
import {
  SectionLead,
  SettingsCard,
  SettingsInput,
  SettingsTextarea,
  SettingsToggle,
} from "./settings-primitives";

function FormRow({
  children,
  description,
  label,
}: {
  children: React.ReactNode;
  description?: string;
  label: string;
}) {
  return (
    <div className={styles.formRow}>
      <div className={styles.formLabel}>
        <p>{label}</p>
        {description ? <span>{description}</span> : null}
      </div>
      <div className={styles.formControl}>{children}</div>
    </div>
  );
}

export function PagesSettings({ pages }: { pages: StaticSettings["pages"] }) {
  return (
    <div className={styles.pagesStack}>
      <SettingsCard className={styles.formCard}>
        <FormRow
          description="Host your site on your own domain"
          label="Custom domain"
        >
          <SettingsInput
            ariaLabel="Custom domain"
            defaultValue={pages.customDomain}
          />
        </FormRow>
        <FormRow
          description="Broken or audited links send visitors here"
          label="Fallback URL"
        >
          <SettingsInput
            ariaLabel="Fallback URL"
            defaultValue={pages.fallbackUrl}
          />
        </FormRow>
        <FormRow description="128 × 128px recommended" label="Favicon">
          <button
            aria-label="Upload favicon"
            className={styles.uploadSquare}
            type="button"
          >
            <Upload size={15} strokeWidth={1.25} />
          </button>
        </FormRow>
        <FormRow
          description="Used when a page is shared"
          label="Social preview"
        >
          <button className={styles.uploadPreview} type="button">
            <Upload size={16} strokeWidth={1.25} />
            <span>Upload image</span>
          </button>
        </FormRow>
        <FormRow label="Page title">
          <SettingsInput
            ariaLabel="Page title"
            defaultValue={pages.pageTitle}
          />
        </FormRow>
        <FormRow label="Page description">
          <SettingsTextarea
            ariaLabel="Page description"
            defaultValue={pages.pageDescription}
            rows={3}
          />
        </FormRow>
      </SettingsCard>

      <section className={styles.connectionSection}>
        <SectionLead>Search engine settings</SectionLead>
        <SettingsCard className={styles.toggleCard}>
          <SettingsToggle
            defaultChecked={pages.allowIndexing}
            label="Allow search engines & LLMs to index assets"
          />
          <div className={styles.divider} />
          <SettingsToggle
            defaultChecked={pages.allowFollowing}
            label="Let search engines follow links on assets"
          />
        </SettingsCard>
      </section>

      <section className={styles.connectionSection}>
        <SectionLead>Additional code snippets</SectionLead>
        <SettingsCard className={styles.formCard}>
          <FormRow label="Head html">
            <SettingsTextarea
              ariaLabel="Head HTML"
              defaultValue={pages.headHtml}
              placeholder="<!-- Add code to the head -->"
            />
          </FormRow>
          <FormRow label="Body html">
            <SettingsTextarea
              ariaLabel="Body HTML"
              defaultValue={pages.bodyHtml}
              placeholder="<!-- Add code before the body closes -->"
            />
          </FormRow>
        </SettingsCard>
      </section>

      <section className={styles.connectionSection}>
        <SectionLead>AI crawler discovery</SectionLead>
        <SettingsCard className={styles.formCard}>
          <FormRow label="LLMs.txt">
            <SettingsTextarea
              ariaLabel="LLMs.txt"
              defaultValue={pages.llmsText}
              placeholder="Add crawler guidance"
            />
          </FormRow>
          <SettingsToggle
            defaultChecked={pages.autoGenerateLlmsText}
            label="Autogenerate LLMs.txt when pages are published"
          />
        </SettingsCard>
      </section>
    </div>
  );
}
