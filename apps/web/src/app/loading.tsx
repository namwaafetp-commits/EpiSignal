import { HomeShell } from "@/components/home-shell";

export default function Loading() {
  return (
    <HomeShell
      apiStatus="loading"
      eventFeed={{ status: "loading", data: null }}
    />
  );
}
