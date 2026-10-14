import { HomeShell } from "@/components/home-shell";
import { getApiStatus } from "@/lib/api-health";
import { getDashboardEvents } from "@/lib/api-dashboard";
import { currentTimestamp } from "@/lib/event-filters";

export default async function Briefing({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [apiStatus, eventFeed, params] = await Promise.all([
    getApiStatus(),
    getDashboardEvents(),
    searchParams,
  ]);
  const query = new URLSearchParams(
    Object.entries(params).filter(
      (entry): entry is [string, string] => typeof entry[1] === "string",
    ),
  ).toString();
  return (
    <HomeShell
      view="briefing"
      apiStatus={apiStatus}
      eventFeed={eventFeed}
      initialQuery={query}
      now={currentTimestamp()}
    />
  );
}
