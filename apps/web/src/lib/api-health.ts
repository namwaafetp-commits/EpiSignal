import type { paths } from "@episignal/contracts";

type ReadyResponse =
  paths["/health/ready"]["get"]["responses"][200]["content"]["application/json"];

export type ApiStatus = "ready" | "unavailable";

export async function getApiStatus(): Promise<ApiStatus> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${baseUrl}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    if (!response.ok) return "unavailable";
    const body = (await response.json()) as ReadyResponse;
    return body.status === "ready" ? "ready" : "unavailable";
  } catch {
    return "unavailable";
  }
}
