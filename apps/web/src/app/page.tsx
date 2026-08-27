import { HomeShell } from "@/components/home-shell";
import { getApiStatus } from "@/lib/api-health";
import { getEvidenceFeed } from "@/lib/api-signals";

export default async function Home() {
  const [apiStatus, evidenceFeed] = await Promise.all([
    getApiStatus(),
    getEvidenceFeed(),
  ]);
  return <HomeShell apiStatus={apiStatus} evidenceFeed={evidenceFeed} />;
}
