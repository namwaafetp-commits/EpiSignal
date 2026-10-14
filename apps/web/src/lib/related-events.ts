import type { DashboardEvent } from "./api-dashboard";
import type { EventDetailResponse } from "./api-events";

export type RelatedEvent = {
  event: DashboardEvent;
  score: number;
  reasons: string[];
};

const NEARBY_REPORTING_DAYS = 14;

/** Same disease group (3) + country (2) + area (1) + host (1) + window (1). */
export const MAX_RELATED_SCORE = 8;

/**
 * Ranks other reported events by shared metadata only — disease group, place,
 * host and reporting window. This is a navigation aid, never a claim that the
 * events are epidemiologically linked.
 */
export function relatedEvents(
  current: Pick<
    EventDetailResponse,
    | "public_id"
    | "disease_group"
    | "country_code"
    | "admin1"
    | "host_sector"
    | "latest_report_at"
  >,
  candidates: readonly DashboardEvent[],
  limit = 5,
): RelatedEvent[] {
  const currentTime = Date.parse(current.latest_report_at);

  return candidates
    .filter((event) => event.public_id !== current.public_id)
    .map((event) => {
      const reasons: string[] = [];
      let score = 0;

      if (
        current.disease_group &&
        event.disease_group === current.disease_group
      ) {
        score += 3;
        reasons.push("Same disease group");
      }
      if (current.country_code && event.country_code === current.country_code) {
        score += 2;
        reasons.push("Same country");
        if (current.admin1 && event.admin1 === current.admin1) {
          score += 1;
          reasons.push("Same area");
        }
      }
      if (current.host_sector && event.host_sector === current.host_sector) {
        score += 1;
        reasons.push("Same host");
      }

      const eventTime = Date.parse(event.latest_report_at);
      if (
        Number.isFinite(currentTime) &&
        Number.isFinite(eventTime) &&
        Math.abs(currentTime - eventTime) <= NEARBY_REPORTING_DAYS * 86_400_000
      ) {
        score += 1;
        reasons.push("Reported nearby in time");
      }

      return { event, score, reasons };
    })
    .filter((candidate) => candidate.score > 0)
    .sort(
      (a, b) =>
        b.score - a.score ||
        Date.parse(b.event.latest_report_at) -
          Date.parse(a.event.latest_report_at),
    )
    .slice(0, limit);
}
