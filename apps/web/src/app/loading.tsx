import { HomeShell } from "@/components/home-shell";

export default function Loading() {
  return (
    <HomeShell
      apiStatus="loading"
      evidenceFeed={{ status: "loading", data: null }}
    />
  );
}
