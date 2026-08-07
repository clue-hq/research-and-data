import { Select } from "@base-ui/react/select";
import { DesignIcon } from "@/components/ui/design-icon";
import styles from "./account-filter-select.module.css";

export interface AccountFilterSelectOption {
  label: string;
  value: string;
}

export function AccountFilterSelect({
  ariaLabel,
  options,
  placeholder = "Select",
  value,
  onValueChange,
}: {
  ariaLabel: string;
  onValueChange: (value: string) => void;
  options: AccountFilterSelectOption[];
  placeholder?: string;
  value: string;
}) {
  return (
    <Select.Root
      items={options}
      onValueChange={(nextValue) => {
        if (typeof nextValue === "string") onValueChange(nextValue);
      }}
      value={value}
    >
      <Select.Trigger aria-label={ariaLabel} className={styles.trigger}>
        <Select.Value className={styles.value} placeholder={placeholder} />
        <Select.Icon className={styles.icon}>
          <DesignIcon name="chevron-down" size={12} />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Positioner
          className={styles.positioner}
          data-clue-account-filter-select=""
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
                  <Select.ItemIndicator className={styles.indicator}>
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
