import { HomeShell } from "@/components/home-shell";
import { getApiStatus } from "@/lib/api-health";
import { getDashboardEvents } from "@/lib/api-dashboard";

export default async function Home() {
  const [apiStatus, eventFeed] = await Promise.all([
    getApiStatus(),
    getDashboardEvents(),
  ]);
  return <HomeShell apiStatus={apiStatus} eventFeed={eventFeed} />;
}
