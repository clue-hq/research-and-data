"use client";

interface AccountCheckboxProps {
  checked: boolean;
  className?: string;
  label: string;
  onChange: () => void;
}

export function AccountCheckbox({
  checked,
  className = "",
  label,
  onChange,
}: AccountCheckboxProps) {
  return (
    <button
      aria-checked={checked}
      aria-label={label}
      className={`relative size-4 rounded-[4px] border-[0.5px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#567644] ${
        checked
          ? "border-[var(--clue-content-neutral)] bg-[var(--clue-content-neutral)]"
          : "border-[#b5bcc6] bg-white"
      } ${className}`}
      onClick={onChange}
      role="checkbox"
      type="button"
    >
      {checked ? (
        <span className="absolute top-[3px] left-[4px] h-[5px] w-[7px] rotate-[-45deg] border-b border-l border-white" />
      ) : null}
    </button>
  );
}
