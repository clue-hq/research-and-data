import type { AccountTableDensity } from "../model/account-table-view";
import readability from "./account-readability.module.css";
import components from "./account-components.module.css";

const densityOptions: Array<{
  label: string;
  value: AccountTableDensity;
}> = [
  { label: "Compact", value: "compact" },
  { label: "Comfortable", value: "comfortable" },
  { label: "Spacious", value: "spacious" },
];

export function TableDensitySelector({
  density,
  onChange,
}: {
  density: AccountTableDensity;
  onChange: (density: AccountTableDensity) => void;
}) {
  return (
    <div
      aria-label="Table row density"
      className={components.segmentedControl}
      role="group"
    >
      {densityOptions.map((option) => {
        const selected = density === option.value;

        return (
          <button
            aria-pressed={selected}
            className={`${readability.actionMedium} ${components.segmentedItem} ${selected ? components.segmentedItemActive : ""}`}
            key={option.value}
            onClick={() => onChange(option.value)}
            type="button"
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
