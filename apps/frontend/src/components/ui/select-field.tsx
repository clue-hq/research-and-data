"use client";

import { Select } from "@base-ui/react/select";
import { DesignIcon } from "@/components/ui/design-icon";
import styles from "./select-field.module.css";

export interface SelectFieldOption {
  label: string;
  value: string;
}

export function SelectField({
  ariaLabel,
  id,
  disabled,
  defaultValue,
  className,
  options,
  placeholder,
  value,
  onValueChange,
}: {
  ariaLabel: string;
  id?: string;
  disabled?: boolean;
  defaultValue?: string;
  className?: string;
  onValueChange: (value: string) => void;
  options: SelectFieldOption[];
  placeholder?: string;
  value?: string;
}) {
  return (
    <Select.Root
      disabled={disabled}
      defaultValue={defaultValue}
      items={options}
      onValueChange={(nextValue) => {
        if (typeof nextValue === "string") onValueChange(nextValue);
      }}
      value={value}
    >
      <Select.Trigger
        id={id}
        aria-label={ariaLabel}
        className={`${styles.trigger} ${className ?? ""}`}
      >
        <Select.Value
          className={styles.value}
          placeholder={placeholder ?? options.find((option) => option.value === "")?.label ?? "Select"}
        />
        <Select.Icon className={styles.icon}>
          <DesignIcon name="chevron-down" size={12} />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Positioner
          className={styles.positioner}
          alignItemWithTrigger={false}
          sideOffset={4}
        >
          <Select.Popup className={styles.popup}>
            <Select.List className={styles.list}>
              {options.map((option) => (
                <Select.Item
                  className={styles.item}
                  key={option.value}
                  label={option.label}
                  value={option.value}
                >
                  <Select.ItemIndicator keepMounted className={styles.indicator}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img alt="" height="7" src="/icons/check.svg" width="9" />
                  </Select.ItemIndicator>
                  <Select.ItemText className={styles.itemText}>
                    {option.label}
                  </Select.ItemText>
                </Select.Item>
              ))}
            </Select.List>
          </Select.Popup>
        </Select.Positioner>
      </Select.Portal>
    </Select.Root>
  );
}
