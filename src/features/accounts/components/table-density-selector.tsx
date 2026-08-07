import type { AccountTableDensity } from "../model/account-table-view";
import readability from "./account-readability.module.css";

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
      className="grid grid-cols-3 gap-0.5 rounded-lg bg-[var(--clue-background-page)] p-0.5"
      role="group"
    >
      {densityOptions.map((option) => {
        const selected = density === option.value;

        return (
          <button
            aria-pressed={selected}
            className={`${readability.actionMedium} flex h-7 items-center justify-center rounded-md px-2 outline-none transition-[background-color,color,box-shadow] duration-150 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#cdd5c4] ${
              selected
                ? "bg-white text-[var(--clue-content-neutral)] shadow-[var(--clue-shadow-low)]"
                : "text-[var(--clue-content-subtle)] hover:bg-white/70"
            }`}
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
