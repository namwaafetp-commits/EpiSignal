import { HomeShell } from "@/components/home-shell";

/**
 * Without this the root fallback would render the map shell while the briefing
 * streams in, flashing the wrong view.
 */
export default function Loading() {
  return (
    <HomeShell
      view="briefing"
      apiStatus="loading"
      eventFeed={{ status: "loading", data: null }}
    />
  );
}
