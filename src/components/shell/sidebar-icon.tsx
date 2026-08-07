import { DesignIcon } from "@/components/ui/design-icon";
import type { SidebarIconName } from "@/config/navigation";

interface SidebarIconProps {
  name: SidebarIconName;
}

export function SidebarIcon({ name }: SidebarIconProps) {
  if (name !== "account") {
    return <DesignIcon name={name} size={16} />;
  }

  return (
    <span aria-hidden="true" className="relative block size-4 shrink-0">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className="absolute top-[7.8px] left-[1.1px] h-[2.34px] w-[13.89px]"
        src="/icons/account-1.svg"
        alt=""
      />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className="absolute top-[8.2px] left-[7.45px] h-[3.11px] w-[1.11px]"
        src="/icons/account-2.svg"
        alt=""
      />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className="absolute top-[1.1px] left-[5px] h-[4.22px] w-[6px]"
        src="/icons/account-3.svg"
        alt=""
      />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className="absolute top-[4.2px] left-[1px] h-[10.44px] w-[14px]"
        src="/icons/account-4.svg"
        alt=""
      />
    </span>
  );
}
