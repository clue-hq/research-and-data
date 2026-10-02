import {
  AtSign,
  BadgeCheck,
  BriefcaseBusiness,
  Building2,
  CalendarPlus,
  CircleDollarSign,
  CircleGauge,
  Clock3,
  Earth,
  Gauge,
  MapPin,
  SlidersHorizontal,
  UserRound,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

const accountColumnIcons: Record<string, LucideIcon> = {
  account: Building2,
  created: CalendarPlus,
  "fit-score": CircleGauge,
  headcount: UsersRound,
  industry: BriefcaseBusiness,
  locations: MapPin,
  modified: Clock3,
  "overall-fit": Gauge,
  owner: UserRound,
  "research-status": BadgeCheck,
  revenue: CircleDollarSign,
  social: AtSign,
  variable: SlidersHorizontal,
  website: Earth,
};

export function AccountColumnIcon({
  name,
  size = 12,
}: {
  name: string;
  size?: number;
}) {
  const Icon = accountColumnIcons[name] ?? SlidersHorizontal;

  return (
    <Icon
      aria-hidden="true"
      className="shrink-0 text-[var(--clue-content-subtle)]"
      size={size}
      strokeWidth={1.5}
    />
  );
}
