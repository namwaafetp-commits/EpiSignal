import type { paths } from "@episignal/contracts";

export type EvidenceFeed =
  paths["/api/v1/signals"]["get"]["responses"][200]["content"]["application/json"];

export type EvidenceFeedState =
  | { status: "ready"; data: EvidenceFeed }
  | { status: "loading"; data: null }
  | { status: "unavailable"; data: null };

export async function getEvidenceFeed(): Promise<EvidenceFeedState> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${baseUrl}/api/v1/signals`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return { status: "unavailable", data: null };
    return {
      status: "ready",
      data: (await response.json()) as EvidenceFeed,
    };
  } catch {
    return { status: "unavailable", data: null };
  }
}
