import Link from "next/link";
import {
  ChevronRight,
  Ellipsis,
  GripVertical,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type {
  DataModelEntity,
  DataModelView,
  StaticSettings,
} from "../model/settings";
import styles from "./settings.module.css";
import { SectionLead, SettingsCard } from "./settings-primitives";

function DataModelTabs({
  active,
  entity,
}: {
  active: DataModelView;
  entity: DataModelEntity;
}) {
  return (
    <div className={styles.tabList}>
      <Link
        className={active === "fields" ? styles.tabActive : styles.tab}
        href={`/settings/data-model/${entity}/fields`}
        prefetch={false}
      >
        Fields
      </Link>
      <span className={styles.tabDisabled}>Relationships</span>
      <Link
        className={active === "display" ? styles.tabActive : styles.tab}
        href={`/settings/data-model/${entity}/display`}
        prefetch={false}
      >
        Display
      </Link>
    </div>
  );
}

function DataModelOverview({
  dataModel,
}: {
  dataModel: StaticSettings["dataModel"];
}) {
  return (
    <SettingsCard className={styles.entityList}>
      {dataModel.entities.map((entity, index) => (
        <div key={entity.id}>
          {index > 0 ? <div className={styles.divider} /> : null}
          <Link
            className={styles.entityRow}
            href={`/settings/data-model/${entity.id}/fields`}
            prefetch={false}
          >
            <span className={styles.entityIcon}>{entity.name.slice(0, 1)}</span>
            <span>{entity.name}</span>
            <ChevronRight
              className={styles.entityChevron}
              size={14}
              strokeWidth={1.4}
            />
          </Link>
        </div>
      ))}
    </SettingsCard>
  );
}

function FieldsView({
  dataModel,
  entity,
}: {
  dataModel: StaticSettings["dataModel"];
  entity: DataModelEntity;
}) {
  return (
    <div className={styles.dataModelStack}>
      <div className={styles.dataModelToolbar}>
        <DataModelTabs active="fields" entity={entity} />
        <Button size="sm" variant="secondary">
          Create field
        </Button>
      </div>
      <div className={styles.fieldTableFrame}>
        <table className={styles.fieldTable}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Editable by</th>
              <th>AI fill</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {dataModel.fields.map((field) => (
              <tr key={field.id}>
                <td>{field.name}</td>
                <td>{field.type}</td>
                <td>{field.editableBy}</td>
                <td>
                  {field.aiFill === "Auto" ? (
                    <span className={styles.aiFill}>
                      <Sparkles size={12} strokeWidth={1.35} />
                      Auto
                    </span>
                  ) : (
                    <span className={styles.mutedText}>—</span>
                  )}
                </td>
                <td>
                  <button
                    aria-label={`More actions for ${field.name}`}
                    className={styles.iconButton}
                    type="button"
                  >
                    <Ellipsis size={14} strokeWidth={1.4} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DisplayGroup({ items, label }: { items: string[]; label: string }) {
  return (
    <div className={styles.displayGroup}>
      <p className={styles.displayGroupLabel}>{label}</p>
      {items.map((item) => (
        <div className={styles.displayItem} key={item}>
          <GripVertical size={14} strokeWidth={1.2} />
          <span>{item}</span>
          {item === "Score" || item === "Last funding" ? (
            <span className={styles.systemBadge}>System</span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function DisplayView({
  dataModel,
  entity,
}: {
  dataModel: StaticSettings["dataModel"];
  entity: DataModelEntity;
}) {
  return (
    <div className={styles.dataModelStack}>
      <DataModelTabs active="display" entity={entity} />
      <div className={styles.displayHeading}>
        <SectionLead description="Drag & drop to reorder how columns are displayed">
          Display order
        </SectionLead>
        <button className={styles.restoreButton} type="button">
          <RotateCcw size={12} strokeWidth={1.35} />
          Restore defaults
        </button>
      </div>
      <SettingsCard className={styles.displayCard}>
        <DisplayGroup
          items={dataModel.display.alwaysShown}
          label="Always shown"
        />
        <div className={styles.divider} />
        <DisplayGroup
          items={dataModel.display.collapsed}
          label="Collapsed by default"
        />
      </SettingsCard>
    </div>
  );
}

export function DataModelSettings({
  dataModel,
  entity,
  view,
}: {
  dataModel: StaticSettings["dataModel"];
  entity?: DataModelEntity;
  view?: DataModelView;
}) {
  if (!entity) return <DataModelOverview dataModel={dataModel} />;
  if (view === "display")
    return <DisplayView dataModel={dataModel} entity={entity} />;
  return <FieldsView dataModel={dataModel} entity={entity} />;
}
