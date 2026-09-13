import {
  Biohazard,
  Brain,
  Bug,
  CircleHelp,
  Clock3,
  Droplet,
  Droplets,
  Hospital,
  Microscope,
  PawPrint,
  Syringe,
  UserRound,
  Wind,
  Zap,
  type LucideIcon,
} from "lucide-react";

// Reporting newer than this reads as breaking; older reads as background.
const FRESH_REPORT_MS = 6 * 60 * 60 * 1000;

const DISEASE_GROUP_ICONS: Record<string, LucideIcon> = {
  respiratory: Wind,
  enteric_food_waterborne: Droplets,
  vector_borne: Bug,
  vaccine_preventable: Syringe,
  viral_hemorrhagic_fever: Biohazard,
  neurologic_invasive: Brain,
  blood_borne_sti: Droplet,
  healthcare_associated_amr: Hospital,
  other_infectious: Microscope,
};

const HOST_SECTOR_ICONS: Record<string, LucideIcon[]> = {
  human: [UserRound],
  animal: [PawPrint],
  both: [UserRound, PawPrint],
};

/**
 * Every icon here is decorative: the adjacent text always carries the same
 * meaning, so nothing is conveyed by icon alone.
 */
export function DiseaseGroupIcon({
  group,
  size = 13,
}: {
  group: string | null | undefined;
  size?: number;
}) {
  const Icon = DISEASE_GROUP_ICONS[group ?? ""] ?? CircleHelp;
  return <Icon size={size} strokeWidth={1.75} aria-hidden="true" />;
}

export function HostSectorIcon({
  host,
  size = 13,
}: {
  host: string | null | undefined;
  size?: number;
}) {
  const icons = HOST_SECTOR_ICONS[host ?? ""] ?? [CircleHelp];
  return (
    <>
      {icons.map((Icon, index) => (
        <Icon key={index} size={size} strokeWidth={1.75} aria-hidden="true" />
      ))}
    </>
  );
}

export function isFreshReport(reportedAt: string, now: number) {
  const timestamp = Date.parse(reportedAt);
  return Number.isFinite(timestamp) && now - timestamp < FRESH_REPORT_MS;
}

export function RecencyIcon({
  reportedAt,
  now,
  size = 13,
}: {
  reportedAt: string;
  now: number;
  size?: number;
}) {
  const fresh = isFreshReport(reportedAt, now);
  const Icon = fresh ? Zap : Clock3;
  return (
    <Icon
      className={fresh ? "recency-icon recency-icon--fresh" : "recency-icon"}
      size={size}
      strokeWidth={1.75}
      aria-hidden="true"
    />
  );
}
