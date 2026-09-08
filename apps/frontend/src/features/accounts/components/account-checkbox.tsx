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
      className={`relative size-4 rounded-[var(--clue-ds-product-component-button-md-radius)] border-[0.5px] transition-colors focus-visible:outline-none focus-visible:shadow-[var(--clue-ds-product-component-button-effect-focus-transparent)] ${
        checked
          ? "border-[var(--clue-content-neutral)] bg-[var(--clue-content-neutral)]"
          : "border-[var(--clue-border-neutral)] bg-[var(--clue-background-neutral)]"
      } ${className}`}
      onClick={onChange}
      role="checkbox"
      type="button"
    >
      {checked ? (
        <span className="absolute top-[3px] left-[4px] h-[5px] w-[7px] rotate-[-45deg] border-b border-l border-[var(--clue-background-neutral)]" />
      ) : null}
    </button>
  );
}
