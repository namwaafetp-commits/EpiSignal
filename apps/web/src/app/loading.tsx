import { HomeShell } from "@/components/home-shell";

export default function Loading() {
  return (
    <HomeShell
      apiStatus="loading"
      radarFeed={{ status: "loading", data: null }}
    />
  );
}
