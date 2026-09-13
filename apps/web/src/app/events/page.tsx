import { redirect } from "next/navigation";

/**
 * The v2 briefing supersedes this list. Old links keep working by carrying the
 * filters that still exist; `status` was retired from the filter set.
 */
const CARRIED_PARAMS: ReadonlyArray<[legacy: string, briefing: string]> = [
  ["disease_group", "disease_group"],
  ["country", "country"],
  ["host_sector", "host"],
  ["disease", "q"],
];

export function briefingHref(params: Record<string, string | undefined>) {
  const query = new URLSearchParams();
  for (const [legacy, briefing] of CARRIED_PARAMS) {
    const value = params[legacy];
    if (value && value !== "all") query.set(briefing, value);
  }
  const serialized = query.toString();
  return serialized ? `/briefing?${serialized}` : "/briefing";
}

export default async function EventsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  redirect(briefingHref(await searchParams));
}
