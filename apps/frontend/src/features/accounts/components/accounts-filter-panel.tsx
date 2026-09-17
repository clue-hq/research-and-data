import type { AccountProject } from "../model/account";
import {
  type AccountFilterField,
  type AccountFilterOperator,
  type AccountFilterRule,
} from "../model/account-query";
import { useAccountsFilterController } from "../hooks/use-accounts-toolbar-controller";
import { AccountFilterSelect } from "./account-filter-select";
import readability from "./account-readability.module.css";
import styles from "./accounts-filter-panel.module.css";

export type AccountFilterOption = { label: string; value: string };

const fieldOptions: Array<{ label: string; value: AccountFilterField }> = [
  { label: "Account name", value: "name" },
  { label: "Project", value: "project" },
  { label: "Research status", value: "researchStatus" },
  { label: "Overall fit", value: "overallFit" },
  { label: "Fit score", value: "fitScore" },
  { label: "Revenue", value: "revenueBand" },
  { label: "Size", value: "employeeBand" },
  { label: "Locations", value: "locationCount" },
];

const operatorLabels: Record<AccountFilterOperator, string> = {
  contains: "contains",
  "does-not-contain": "does not contain",
  "greater-than": "is greater than",
  is: "is",
  "is-not": "is not",
  "less-than": "is less than",
};

function operatorOptions(field: AccountFilterField) {
  const operators: AccountFilterOperator[] =
    field === "fitScore" || field === "locationCount"
      ? ["greater-than", "is", "less-than"]
      : field === "name"
        ? ["contains", "is", "does-not-contain"]
        : ["is", "is-not"];

  return operators.map((operator) => ({
    label: operatorLabels[operator],
    value: operator,
  }));
}

function valueOptions(
  field: AccountFilterField,
  projects: AccountProject[],
  researchStatusOptions: AccountFilterOption[],
) {
  if (field === "project") {
    return projects.map((project) => ({
      label: project.name,
      value: project.id,
    }));
  }
  if (field === "researchStatus") {
    // The wording is the backend's `researchStatusLabel`, collected off the rows
    // the table is showing; the browser owns no status vocabulary.
    return researchStatusOptions;
  }
  if (field === "overallFit") {
    return ["High", "Medium", "Low"].map((value) => ({
      label: value,
      value,
    }));
  }
  return null;
}

function RuleValue({
  onChange,
  projects,
  researchStatusOptions,
  rule,
}: {
  onChange: (value: string) => void;
  projects: AccountProject[];
  researchStatusOptions: AccountFilterOption[];
  rule: AccountFilterRule;
}) {
  const options = valueOptions(rule.field, projects, researchStatusOptions);
  if (options) {
    return (
      <AccountFilterSelect
        ariaLabel={`${fieldOptions.find((field) => field.value === rule.field)?.label} value`}
        onValueChange={onChange}
        options={options}
        placeholder={rule.field === "project" ? "Select project" : "Select value"}
        value={rule.value}
      />
    );
  }

  const numeric = rule.field === "fitScore" || rule.field === "locationCount";
  return (
    <input
      aria-label={`${fieldOptions.find((field) => field.value === rule.field)?.label} value`}
      className={styles.valueInput}
      inputMode={numeric ? "numeric" : "text"}
      min={numeric ? 0 : undefined}
      onChange={(event) => onChange(event.target.value)}
      placeholder={numeric ? "Enter number" : "Enter value"}
      type={numeric ? "number" : "text"}
      value={rule.value}
    />
  );
}

export function AccountsFilterPanel({
  filters,
  onFiltersChange,
  projects,
  researchStatusOptions,
}: {
  filters: AccountFilterRule[];
  onFiltersChange: (filters: AccountFilterRule[]) => void;
  projects: AccountProject[];
  researchStatusOptions: AccountFilterOption[];
}) {
  const controller = useAccountsFilterController(filters, onFiltersChange);

  return (
    <section
      aria-label="Account filters"
      className={`${readability.popoverEnter} ${styles.panel}`}
    >
      <div className={styles.header}>
        <h2 className={styles.title}>Filter accounts</h2>
        <button
          className={styles.clearButton}
          disabled={!controller.activeRuleCount}
          onClick={controller.clearRules}
          type="button"
        >
          Clear all
        </button>
      </div>

      <div className={styles.rules}>
        {filters.map((rule, index) => (
          <div className={styles.rule} key={rule.id}>
            {index === 0 ? (
              <span className={styles.whereLabel}>Where</span>
            ) : (
              <AccountFilterSelect
                ariaLabel={`Condition ${index + 1} join`}
                onValueChange={(value) =>
                  controller.updateRule(rule.id, {
                    join: value === "or" ? "or" : "and",
                  })
                }
                options={[
                  { label: "And", value: "and" },
                  { label: "Or", value: "or" },
                ]}
                value={rule.join}
              />
            )}

            <div className={styles.controls}>
              <AccountFilterSelect
                ariaLabel={`Condition ${index + 1} field`}
                onValueChange={(value) =>
                  controller.updateField(rule.id, value as AccountFilterField)
                }
                options={fieldOptions}
                value={rule.field}
              />
              <AccountFilterSelect
                ariaLabel={`Condition ${index + 1} operator`}
                onValueChange={(value) =>
                  controller.updateRule(rule.id, {
                    operator: value as AccountFilterOperator,
                  })
                }
                options={operatorOptions(rule.field)}
                value={rule.operator}
              />
              <RuleValue
                onChange={(value) => controller.updateRule(rule.id, { value })}
                projects={projects}
                researchStatusOptions={researchStatusOptions}
                rule={rule}
              />
            </div>

            {filters.length > 1 ? (
              <button
                aria-label={`Delete condition ${index + 1}`}
                className={styles.deleteButton}
                onClick={() => controller.removeRule(rule.id)}
                type="button"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img alt="" height="11" src="/icons/filters/trash.svg" width="10" />
              </button>
            ) : (
              <span aria-hidden="true" className={styles.deletePlaceholder} />
            )}
          </div>
        ))}
      </div>

      <div className={styles.footer}>
        <button
          className={styles.addButton}
          onClick={controller.addRule}
          type="button"
        >
          <span aria-hidden="true" className={styles.plusIcon}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img alt="" height="1" src="/icons/filters/plus-horizontal.svg" width="9" />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img alt="" height="9" src="/icons/filters/plus-vertical.svg" width="1" />
          </span>
          Add condition
        </button>
      </div>
    </section>
  );
}
