"use client";

interface AccountCheckboxProps {
  checked: boolean;
  className?: string;
  indeterminate?: boolean;
  label: string;
  onChange: () => void;
}

export function AccountCheckbox({
  checked,
  className = "",
  indeterminate = false,
  label,
  onChange,
}: AccountCheckboxProps) {
  return (
    <button
      aria-checked={indeterminate ? "mixed" : checked}
      aria-label={label}
      className={`relative size-4 rounded-[4px] border-[0.5px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#567644] ${
        checked || indeterminate
          ? "border-[var(--clue-content-neutral)] bg-[var(--clue-content-neutral)]"
          : "border-[#b5bcc6] bg-white"
      } ${className}`}
      onClick={onChange}
      role="checkbox"
      type="button"
    >
      {indeterminate ? (
        <span className="absolute top-[7px] left-[3px] h-px w-2 bg-white" />
      ) : checked ? (
        <span className="absolute top-[3px] left-[4px] h-[5px] w-[7px] rotate-[-45deg] border-b border-l border-white" />
      ) : null}
    </button>
  );
}
