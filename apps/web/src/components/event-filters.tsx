"use client";

import { useEffect, useRef, useState } from "react";
import {
  Clock3,
  SlidersHorizontal,
  RotateCcw,
  Search,
  Bug,
  UserRound,
  Globe2,
} from "lucide-react";
import type { DashboardEvent } from "../lib/api-dashboard";
import { countryFlag, countryName } from "../lib/country";
import { DISEASE_GROUP_OPTIONS } from "../lib/surveillance-labels";
import {
  invalidRange,
  periodOptions,
  PERIOD_LABELS,
  type EventFilters,
  type FilterView,
} from "../lib/event-filters";

const SEARCH_DEBOUNCE_MS = 250;

export function FilterBar({
  events,
  filters,
  onChange,
  onReset,
  view,
}: {
  events: readonly DashboardEvent[];
  filters: EventFilters;
  onChange: (key: keyof EventFilters, value: string) => void;
  onReset: () => void;
  view: FilterView;
}) {
  const [expanded, setExpanded] = useState(false);
  const [countryDraft, setCountryDraft] = useState("");

  // Typing re-filters the whole feed and rewrites history, so commit on a
  // pause rather than per keystroke. The ref lets outside changes (reset,
  // back/forward, a shared URL) resync without clobbering in-flight typing.
  const [searchDraft, setSearchDraft] = useState(filters.q);
  const committedSearch = useRef(filters.q);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (filters.q !== committedSearch.current) {
      committedSearch.current = filters.q;
      setSearchDraft(filters.q);
    }
  }, [filters.q]);
  useEffect(
    () => () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    },
    [],
  );
  const countries = [
    ...new Set([
      ...events.map((e) => e.country_code).filter((c): c is string => !!c),
      ...(filters.country ? [filters.country] : []),
    ]),
  ].sort((a, b) => countryName(a).localeCompare(countryName(b)));
  return (
    <section
      className={`v2-filters ${view === "map" ? "v2-filters--compact" : ""} ${expanded ? "is-expanded" : ""}`}
      aria-label="Event filters"
    >
      <div className="filter-primary">
        <label>
          <span>
            <Clock3 size={14} aria-hidden="true" />
            Period
          </span>
          <select
            value={filters.period}
            onChange={(e) => onChange("period", e.target.value)}
          >
            {periodOptions(view).map((p) => (
              <option value={p} key={p}>
                {PERIOD_LABELS[p]}
              </option>
            ))}
          </select>
        </label>
        <label className="filter-disease">
          <span>
            <Bug size={14} aria-hidden="true" />
            Disease group
          </span>
          <select
            value={filters.disease_group}
            onChange={(e) => onChange("disease_group", e.target.value)}
          >
            {DISEASE_GROUP_OPTIONS.map((o) => (
              <option value={o.value === "all" ? "" : o.value} key={o.value}>
                {o.label}
              </option>
            ))}
            {filters.disease_group &&
              !DISEASE_GROUP_OPTIONS.some(
                (o) => o.value === filters.disease_group,
              ) && (
                <option value={filters.disease_group}>
                  {filters.disease_group.replaceAll("_", " ")}
                </option>
              )}
          </select>
        </label>
        <button
          className="filter-disclosure"
          type="button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-controls="advanced-filters"
        >
          <SlidersHorizontal size={17} aria-hidden="true" />
          <span>Filters</span>
          {[filters.host, filters.country, filters.q].filter(Boolean).length >
            0 && (
            <span className="filter-count">
              {
                [filters.host, filters.country, filters.q].filter(Boolean)
                  .length
              }
            </span>
          )}
        </button>
      </div>
      <div id="advanced-filters" className="filter-advanced">
        <label>
          <span>
            <UserRound size={14} aria-hidden="true" />
            Host
          </span>
          <select
            value={filters.host}
            onChange={(e) => onChange("host", e.target.value)}
          >
            <option value="">All hosts</option>
            <option value="human">Human</option>
            <option value="animal">Animal</option>
            <option value="both">Human / Animal only</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <label>
          <span>
            <Globe2 size={14} aria-hidden="true" />
            Geography
          </span>
          {/* Typing beats scrolling once the feed covers many countries. */}
          <input
            type="text"
            list="country-options"
            placeholder="All countries"
            value={
              filters.country ? countryName(filters.country) : countryDraft
            }
            onChange={(e) => {
              const typed = e.target.value;
              setCountryDraft(typed);
              const match = countries.find(
                (c) =>
                  countryName(c).toLowerCase() === typed.trim().toLowerCase() ||
                  c === typed.trim().toUpperCase(),
              );
              onChange("country", match ?? "");
            }}
          />
          <datalist id="country-options">
            {countries.map((c) => (
              <option value={countryName(c)} key={c}>
                {countryFlag(c)}
              </option>
            ))}
          </datalist>
        </label>
        <label className="filter-search">
          <span>
            <Search size={14} aria-hidden="true" />
            Search
          </span>
          <input
            id="event-search"
            type="search"
            placeholder="Disease, place, headline…"
            value={searchDraft}
            onChange={(e) => {
              const typed = e.target.value;
              setSearchDraft(typed);
              if (searchTimer.current) clearTimeout(searchTimer.current);
              searchTimer.current = setTimeout(() => {
                committedSearch.current = typed;
                onChange("q", typed);
              }, SEARCH_DEBOUNCE_MS);
            }}
          />
        </label>
      </div>
      {filters.period === "custom" && (
        <div className="filter-dates">
          <label>
            <span>From</span>
            <input
              type="date"
              value={filters.from}
              onChange={(e) => onChange("from", e.target.value)}
            />
          </label>
          <label>
            <span>To</span>
            <input
              type="date"
              value={filters.to}
              onChange={(e) => onChange("to", e.target.value)}
            />
          </label>
          <span>Dates in UTC</span>
          {invalidRange(filters) && (
            <p role="alert">
              Choose a valid date range: start must be on or before end.
            </p>
          )}
        </div>
      )}
      <button
        type="button"
        className="filter-reset"
        onClick={onReset}
        aria-label="Reset filters"
        title="Reset filters"
      >
        <RotateCcw size={17} aria-hidden="true" />
      </button>
    </section>
  );
}
