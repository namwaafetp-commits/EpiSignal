import { HomeShell } from "@/components/home-shell";
import { getApiStatus } from "@/lib/api-health";
import { getRadarFeed } from "@/lib/api-radar";

export default async function Home() {
  const [apiStatus, radarFeed] = await Promise.all([
    getApiStatus(),
    getRadarFeed({ hours: 48, limit: 50 }),
  ]);
  return <HomeShell apiStatus={apiStatus} radarFeed={radarFeed} />;
}
