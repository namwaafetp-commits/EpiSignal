import { HomeShell } from "@/components/home-shell";
import { getApiStatus } from "@/lib/api-health";

export default async function Home() {
  const apiStatus = await getApiStatus();
  return <HomeShell apiStatus={apiStatus} />;
}
