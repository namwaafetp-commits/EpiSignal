"use client";

import { useState } from "react";
import {
  getReviewQueue,
  resolveReview,
  type ReviewQueueItem,
  type ReviewQueueState,
  type ResolveReviewRequest,
} from "../lib/api-reviews";

const REASON_LABELS: Record<string, string> = {
  retrieval_failed: "Retrieval Failed",
  extraction_rejected: "Extraction Rejected",
  disease_unresolved: "Disease Unresolved",
  location_unresolved: "Location Unresolved",
  event_match_ambiguous: "Event Match Ambiguous",
  content_integrity: "Content Integrity",
  legacy_unclassified: "Legacy Unclassified",
};

const REASON_DESCRIPTIONS: Record<string, string> = {
  retrieval_failed:
    "Source document retrieval failed or timed out. Retry retrieval or dismiss if unreachable.",
  extraction_rejected:
    "AI structured extraction failed validation or confidence threshold. Retry extraction or dismiss.",
  disease_unresolved:
    "The extracted disease term could not be matched to canonical disease ontology. Select a canonical disease.",
  location_unresolved:
    "Geocoding precision or place matching was insufficient. Retry geocoding or dismiss.",
  event_match_ambiguous:
    "Signal matches existing outbreak events above ambiguity threshold. Link to an existing event or create a new event.",
  content_integrity:
    "Source text or signal metadata failed integrity validation. Dismiss or reprocess.",
  legacy_unclassified:
    "Signal was flagged for review before typed causes were introduced.",
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export function AdminReviewQueue() {
  const [token, setToken] = useState("");
  const [reviewedBy, setReviewedBy] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [reviewedByInput, setReviewedByInput] = useState("");

  const [queueState, setQueueState] = useState<
    ReviewQueueState | { status: "locked"; data: null }
  >({ status: "locked", data: null });

  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [pendingCaseId, setPendingCaseId] = useState<string | null>(null);

  // Decision form states
  const [actionChoice, setActionChoice] = useState<string>("");
  const [selectedEventId, setSelectedEventId] = useState<string>("");
  const [selectedDiseaseId, setSelectedDiseaseId] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const [dismissConfirmed, setDismissConfirmed] = useState<boolean>(false);

  const [statusMessage, setStatusMessage] = useState<{
    type: "success" | "error" | "conflict";
    text: string;
  } | null>(null);

  const items = queueState.status === "ready" && queueState.data ? queueState.data.items : [];
  const diseaseOptions = queueState.status === "ready" && queueState.data ? queueState.data.disease_options : [];

  const activeCase: ReviewQueueItem | null =
    items.find((item) => item.case_id === selectedCaseId) ??
    items[0] ??
    null;

  function selectCase(caseItem: ReviewQueueItem) {
    setSelectedCaseId(caseItem.case_id);
    const allowed = caseItem.allowed_resolutions ?? [];
    setActionChoice(allowed.length > 0 ? allowed[0] : "");
    setSelectedEventId(
      caseItem.candidate_events && caseItem.candidate_events.length > 0
        ? caseItem.candidate_events[0].event_id
        : ""
    );
    setSelectedDiseaseId("");
    setNote("");
    setDismissConfirmed(false);
  }

  async function handleUnlock(e: React.FormEvent) {
    e.preventDefault();
    if (!tokenInput.trim() || !reviewedByInput.trim()) return;

    setToken(tokenInput.trim());
    setReviewedBy(reviewedByInput.trim());
    setQueueState({ status: "loading", data: null });
    setStatusMessage(null);

    const result = await getReviewQueue(tokenInput.trim());
    setQueueState(result);

    if (result.status === "ready" && result.data.items.length > 0) {
      selectCase(result.data.items[0]);
    }
  }

  async function handleReloadQueue() {
    if (!token) return;
    setQueueState({ status: "loading", data: null });
    const result = await getReviewQueue(token);
    setQueueState(result);
    if (result.status === "ready" && result.data.items.length > 0) {
      selectCase(result.data.items[0]);
    }
  }

  async function handleResolve(actionToExecute?: string, e?: React.FormEvent) {
    if (e) e.preventDefault();
    if (!activeCase || !token || !reviewedBy) return;

    const action = actionToExecute || actionChoice;
    let commandPayload: ResolveReviewRequest;

    if (action === "link_event") {
      const eid =
        selectedEventId ||
        (activeCase.candidate_events && activeCase.candidate_events.length > 0
          ? activeCase.candidate_events[0].event_id
          : "");
      if (!eid) {
        setStatusMessage({
          type: "error",
          text: "Please select a target candidate event to link.",
        });
        return;
      }
      commandPayload = {
        action: "link_event",
        event_id: eid,
        note: note.trim() || null,
      };
    } else if (action === "create_event") {
      commandPayload = {
        action: "create_event",
        verification_status: "unverified",
        note: note.trim() || null,
      };
    } else if (action === "assign_disease") {
      if (!selectedDiseaseId) {
        setStatusMessage({
          type: "error",
          text: "Please select a canonical disease from the catalog.",
        });
        return;
      }
      commandPayload = {
        action: "assign_disease",
        disease_id: selectedDiseaseId,
        note: note.trim() || null,
      };
    } else if (action === "retry_retrieval") {
      commandPayload = {
        action: "retry_retrieval",
        note: note.trim() || null,
      };
    } else if (action === "retry_extraction") {
      commandPayload = {
        action: "retry_extraction",
        note: note.trim() || null,
      };
    } else if (action === "retry_geocoding") {
      commandPayload = {
        action: "retry_geocoding",
        note: note.trim() || null,
      };
    } else if (action === "dismiss") {
      if (!note.trim()) {
        setStatusMessage({
          type: "error",
          text: "A rationale note is required to dismiss a signal.",
        });
        return;
      }
      if (!dismissConfirmed) {
        setStatusMessage({
          type: "error",
          text: "Please confirm signal dismissal by checking the confirmation box.",
        });
        return;
      }
      commandPayload = {
        action: "dismiss",
        note: note.trim(),
      };
    } else {
      setStatusMessage({
        type: "error",
        text: "Invalid resolution action selected.",
      });
      return;
    }

    setPendingCaseId(activeCase.case_id);
    setStatusMessage(null);

    const res = await resolveReview(token, activeCase.case_id, commandPayload);
    setPendingCaseId(null);

    if (res.status === "success") {
      setStatusMessage({
        type: "success",
        text: `Case ${activeCase.case_id.slice(0, 8)} resolved successfully (${action.replace(/_/g, " ")}).`,
      });

      // Remove the case from current queue state
      if (queueState.status === "ready" && queueState.data) {
        const remaining = queueState.data.items.filter(
          (item) => item.case_id !== activeCase.case_id
        );
        const updatedTotal = Math.max(0, queueState.data.total_open_cases - 1);
        setQueueState({
          status: "ready",
          data: {
            ...queueState.data,
            items: remaining,
            total_open_cases: updatedTotal,
          },
        });
        if (remaining.length > 0) {
          selectCase(remaining[0]);
        } else {
          setSelectedCaseId(null);
        }
      }
    } else if (res.status === "conflict") {
      setStatusMessage({
        type: "conflict",
        text: `Conflict: ${res.message}`,
      });
    } else if (res.status === "unauthorized") {
      setStatusMessage({
        type: "error",
        text: `Unauthorized: ${res.message}`,
      });
    } else {
      setStatusMessage({
        type: "error",
        text: res.message || "Action failed. Please try again.",
      });
    }
  }

  // 1. Locked State
  if (queueState.status === "locked") {
    return (
      <div className="max-w-md mx-auto my-12 p-8 rounded-xl bg-slate-900 border border-slate-800 text-slate-100 shadow-2xl">
        <h2 className="text-xl font-bold text-cyan-400 mb-2">
          Admin Authentication
        </h2>
        <p className="text-sm text-slate-400 mb-6">
          Enter administrator secret token and operator identifier to review
          and resolve signals requiring human judgment.
        </p>

        <form onSubmit={handleUnlock} className="space-y-4">
          <div>
            <label
              htmlFor="adminToken"
              className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-1"
            >
              Admin Token
            </label>
            <input
              id="adminToken"
              name="adminToken"
              type="password"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="Enter secret token"
              required
              className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-400"
            />
          </div>

          <div>
            <label
              htmlFor="reviewedBy"
              className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-1"
            >
              Operator Name / ID
            </label>
            <input
              id="reviewedBy"
              name="reviewedBy"
              type="text"
              value={reviewedByInput}
              onChange={(e) => setReviewedByInput(e.target.value)}
              placeholder="e.g. Dr. Jane Doe"
              required
              className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-400"
            />
          </div>

          <button
            type="submit"
            className="w-full py-2 px-4 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold rounded-lg transition-colors"
          >
            Unlock Review Queue
          </button>
        </form>
      </div>
    );
  }

  // 2. Loading State
  if (queueState.status === "loading") {
    return (
      <div className="text-center py-16 text-slate-400">
        <p className="text-lg">Loading manual review queue…</p>
      </div>
    );
  }

  // 3. Unauthorized State
  if (queueState.status === "unauthorized") {
    return (
      <div className="max-w-md mx-auto my-12 p-8 rounded-xl bg-slate-900 border border-rose-900/50 text-slate-100 text-center">
        <h2 className="text-xl font-bold text-rose-400 mb-2">
          Unauthorized Access
        </h2>
        <p className="text-sm text-slate-400 mb-6">
          The provided admin token was rejected or is not authorized to review
          signals.
        </p>
        <button
          onClick={() =>
            setQueueState({ status: "locked", data: null })
          }
          className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-cyan-400 rounded-lg text-sm font-semibold transition-colors"
        >
          Re-enter Credentials
        </button>
      </div>
    );
  }

  // 4. Unavailable State
  if (queueState.status === "unavailable") {
    return (
      <div className="max-w-md mx-auto my-12 p-8 rounded-xl bg-slate-900 border border-amber-900/50 text-slate-100 text-center">
        <h2 className="text-xl font-bold text-amber-400 mb-2">
          Service Unavailable
        </h2>
        <p className="text-sm text-slate-400 mb-6">
          The review API could not be reached. Please verify backend service
          health and connectivity.
        </p>
        <button
          onClick={handleReloadQueue}
          className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-cyan-400 rounded-lg text-sm font-semibold transition-colors"
        >
          Retry Connection
        </button>
      </div>
    );
  }

  // 5. Empty Queue
  if (items.length === 0) {
    return (
      <div className="text-center py-16 px-4">
        <div className="max-w-md mx-auto p-8 rounded-xl bg-slate-900 border border-slate-800 text-slate-100">
          <h2 className="text-xl font-bold text-emerald-400 mb-2">
            Queue Clear
          </h2>
          <p className="text-sm text-slate-400 mb-4">
            No signals are currently awaiting manual review. All ingested signals
            have either matched cleanly or were automatically resolved.
          </p>
          <button
            onClick={handleReloadQueue}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-cyan-400 rounded-lg text-xs font-semibold"
          >
            Refresh Queue
          </button>
        </div>
      </div>
    );
  }

  const isDismissDisabled =
    pendingCaseId === activeCase?.case_id ||
    !note.trim() ||
    !dismissConfirmed;

  // 6. Ready Workspace
  return (
    <div className="space-y-6">
      {/* Top Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl bg-slate-900 border border-slate-800">
        <div>
          <h2 className="text-lg font-bold text-slate-100">
            Open Review Cases ({queueState.data?.total_open_cases ?? 0})
          </h2>
          <p className="text-xs text-slate-400">
            Operator: <span className="text-cyan-400 font-medium">{reviewedBy}</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleReloadQueue}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold transition-colors"
          >
            Refresh
          </button>
          <button
            onClick={() => {
              setToken("");
              setReviewedBy("");
              setQueueState({ status: "locked", data: null });
            }}
            className="px-3 py-1.5 bg-slate-800/60 hover:bg-rose-950/40 text-slate-400 hover:text-rose-300 rounded-lg text-xs font-semibold transition-colors"
          >
            Lock
          </button>
        </div>
      </div>

      {/* Status Notifications Area */}
      <div aria-live="polite" className="min-h-[2rem]">
        {statusMessage && (
          <div
            className={`p-3 rounded-lg text-sm font-medium border ${
              statusMessage.type === "success"
                ? "bg-emerald-950/60 border-emerald-800 text-emerald-300"
                : statusMessage.type === "conflict"
                ? "bg-amber-950/60 border-amber-800 text-amber-300"
                : "bg-rose-950/60 border-rose-800 text-rose-300"
            }`}
          >
            {statusMessage.text}
          </div>
        )}
      </div>

      {/* Main Review Console Grid */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-start">
        {/* Left: Case Rail */}
        <aside className="md:col-span-5 space-y-3" aria-label="Review Cases Rail">
          {items.map((item) => {
            const isSelected = activeCase?.case_id === item.case_id;
            return (
              <button
                key={item.case_id}
                type="button"
                onClick={() => selectCase(item)}
                className={`w-full text-left p-4 rounded-xl border transition-all ${
                  isSelected
                    ? "bg-slate-900/90 border-cyan-500 shadow-md shadow-cyan-950/20"
                    : "bg-slate-900/40 border-slate-800 hover:border-slate-700 hover:bg-slate-900/60"
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-slate-800 text-cyan-300 border border-slate-700">
                    {REASON_LABELS[item.reason] ?? item.reason}
                  </span>
                  <span className="text-[11px] text-slate-500 font-mono">
                    {formatDate(item.opened_at)}
                  </span>
                </div>

                <h3 className="text-sm font-semibold text-slate-200 line-clamp-2 mb-1">
                  {item.title}
                </h3>

                <div className="flex items-center gap-3 text-xs text-slate-400">
                  <span>{item.source_name}</span>
                  {item.canonical_disease && (
                    <span className="text-cyan-400 font-medium">
                      {item.canonical_disease}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </aside>

        {/* Right: Decision Workspace */}
        {activeCase && (
          <section
            className="md:col-span-7 bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-6"
            aria-label="Decision Workspace"
          >
            {/* Case Header */}
            <div>
              <div className="inline-block px-2.5 py-1 rounded text-xs font-bold uppercase tracking-wider bg-cyan-950 border border-cyan-800 text-cyan-300 mb-2">
                {REASON_LABELS[activeCase.reason] ?? activeCase.reason}
              </div>
              <h2 className="text-lg font-bold text-slate-100 mb-2">
                {activeCase.title}
              </h2>
              <p className="text-xs text-slate-400">
                {REASON_DESCRIPTIONS[activeCase.reason]}
              </p>
            </div>

            {/* Signal Provenance & Metadata */}
            <div className="p-4 rounded-lg bg-slate-950 border border-slate-800 text-xs space-y-2">
              <div className="grid grid-cols-2 gap-2 text-slate-300">
                <div>
                  <span className="text-slate-500 block">Source Name:</span>
                  <span className="font-medium text-slate-200">
                    {activeCase.source_name}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block">First Seen:</span>
                  <span>{formatDate(activeCase.first_seen_at)}</span>
                </div>
                <div>
                  <span className="text-slate-500 block">Source URL:</span>
                  <a
                    href={activeCase.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-cyan-400 hover:underline truncate block"
                  >
                    {activeCase.source_url}
                  </a>
                </div>
                <div>
                  <span className="text-slate-500 block">Retrieval Attempts:</span>
                  <span>{activeCase.retrieval_attempts}</span>
                </div>
              </div>

              {/* Disease info */}
              <div className="pt-2 border-t border-slate-800 grid grid-cols-2 gap-2">
                <div>
                  <span className="text-slate-500 block">Extracted Disease Text:</span>
                  <span className="text-slate-300">
                    {activeCase.extracted_disease_text || "None extracted"}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block">Canonical Disease:</span>
                  <span className="text-cyan-300 font-medium">
                    {activeCase.canonical_disease || "Unassigned"}
                  </span>
                </div>
              </div>

              {/* Locations */}
              {activeCase.locations && activeCase.locations.length > 0 && (
                <div className="pt-2 border-t border-slate-800">
                  <span className="text-slate-500 block mb-1">Locations:</span>
                  <div className="flex flex-wrap gap-1.5">
                    {activeCase.locations.map((loc, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-300 text-[11px]"
                      >
                        {loc.resolved_name || loc.place_name || loc.country_name || "Location"}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Decision Action Form */}
            <form onSubmit={(e) => handleResolve(actionChoice, e)} className="space-y-4">
              <fieldset className="space-y-4">
                <legend className="text-sm font-bold text-slate-200 mb-2">
                  Resolution Decision
                </legend>

                {/* Ambiguous Event Candidates */}
                {activeCase.reason === "event_match_ambiguous" &&
                  activeCase.candidate_events &&
                  activeCase.candidate_events.length > 0 && (
                    <div className="space-y-2">
                      <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Candidate Matching Events
                      </label>
                      <div className="space-y-2">
                        {activeCase.candidate_events.map((cand) => (
                          <label
                            key={cand.event_id}
                            className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                              selectedEventId === cand.event_id
                                ? "bg-slate-950 border-cyan-500 text-slate-100"
                                : "bg-slate-950/60 border-slate-800 text-slate-300 hover:border-slate-700"
                            }`}
                          >
                            <input
                              type="radio"
                              name="candidateEvent"
                              value={cand.event_id}
                              checked={selectedEventId === cand.event_id}
                              onChange={() => {
                                setSelectedEventId(cand.event_id);
                                setActionChoice("link_event");
                              }}
                              className="mt-1"
                            />
                            <div className="text-xs space-y-0.5">
                              <div className="flex items-center gap-2">
                                <span className="font-mono font-bold text-cyan-400">
                                  {cand.public_id}
                                </span>
                                <span className="text-slate-500">
                                  Score: {cand.match_score.toFixed(2)}
                                </span>
                              </div>
                              <p className="font-medium text-slate-200">
                                {cand.title}
                              </p>
                              <span className="inline-block text-[10px] text-slate-400 uppercase">
                                Status: {cand.verification_status}
                              </span>
                            </div>
                          </label>
                        ))}
                      </div>
                    </div>
                  )}

                {/* Disease Selection for disease_unresolved */}
                {activeCase.reason === "disease_unresolved" && (
                  <div>
                    <label
                      htmlFor="diseaseSelect"
                      className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1"
                    >
                      Select Canonical Disease
                    </label>
                    <select
                      id="diseaseSelect"
                      value={selectedDiseaseId}
                      onChange={(e) => {
                        setSelectedDiseaseId(e.target.value);
                        setActionChoice("assign_disease");
                      }}
                      className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-slate-200 text-xs focus:outline-none focus:border-cyan-400"
                    >
                      <option value="">-- Choose canonical disease --</option>
                      {diseaseOptions.map((opt) => (
                        <option key={opt.id} value={opt.id}>
                          {opt.canonical_name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {/* Rationale Note */}
                <div>
                  <label
                    htmlFor="decisionNote"
                    className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1"
                  >
                    Rationale Note
                  </label>
                  <textarea
                    id="decisionNote"
                    name="decisionNote"
                    rows={2}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Provide operator context or reasoning..."
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-slate-200 text-xs placeholder-slate-600 focus:outline-none focus:border-cyan-400"
                  />
                </div>

                {/* Dismissal confirmation checkbox */}
                <div className="p-3 rounded-lg bg-rose-950/30 border border-rose-900/50">
                  <label
                    htmlFor="confirmDismissal"
                    className="flex items-center gap-2 text-xs text-rose-300 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      id="confirmDismissal"
                      checked={dismissConfirmed}
                      onChange={(e) => setDismissConfirmed(e.target.checked)}
                    />
                    Confirm dismissal (signal will not form an outbreak event)
                  </label>
                </div>
              </fieldset>

              {/* Action Buttons */}
              <div className="flex flex-wrap gap-2 pt-2 border-t border-slate-800">
                {activeCase.reason === "event_match_ambiguous" && (
                  <>
                    <button
                      type="button"
                      onClick={(e) => {
                        handleResolve("link_event", e);
                      }}
                      disabled={pendingCaseId === activeCase.case_id || !selectedEventId}
                      className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-slate-950 font-bold rounded-lg text-xs transition-colors"
                    >
                      Link to Selected Event
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        handleResolve("create_event", e);
                      }}
                      disabled={pendingCaseId === activeCase.case_id}
                      className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-cyan-300 font-semibold rounded-lg text-xs transition-colors"
                    >
                      Create as New Event
                    </button>
                  </>
                )}

                {activeCase.reason === "disease_unresolved" && (
                  <button
                    type="button"
                    onClick={(e) => {
                      handleResolve("assign_disease", e);
                    }}
                    disabled={pendingCaseId === activeCase.case_id || !selectedDiseaseId}
                    className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-slate-950 font-bold rounded-lg text-xs transition-colors"
                  >
                    Assign Disease and Match
                  </button>
                )}

                {activeCase.reason === "retrieval_failed" && (
                  <button
                    type="button"
                    onClick={(e) => {
                      handleResolve("retry_retrieval", e);
                    }}
                    disabled={pendingCaseId === activeCase.case_id}
                    className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-slate-950 font-bold rounded-lg text-xs transition-colors"
                  >
                    Retry Document Retrieval
                  </button>
                )}

                {activeCase.reason === "extraction_rejected" && (
                  <button
                    type="button"
                    onClick={(e) => {
                      handleResolve("retry_extraction", e);
                    }}
                    disabled={pendingCaseId === activeCase.case_id}
                    className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-slate-950 font-bold rounded-lg text-xs transition-colors"
                  >
                    Retry Fact Extraction
                  </button>
                )}

                {activeCase.reason === "location_unresolved" && (
                  <button
                    type="button"
                    onClick={(e) => {
                      handleResolve("retry_geocoding", e);
                    }}
                    disabled={pendingCaseId === activeCase.case_id}
                    className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-slate-950 font-bold rounded-lg text-xs transition-colors"
                  >
                    Retry Geocoding
                  </button>
                )}

                {/* Dismiss Button */}
                <button
                  type="button"
                  onClick={(e) => {
                    handleResolve("dismiss", e);
                  }}
                  disabled={isDismissDisabled}
                  className="px-4 py-2 bg-rose-950 hover:bg-rose-900 border border-rose-800 disabled:opacity-40 text-rose-300 font-semibold rounded-lg text-xs transition-colors ml-auto"
                >
                  Dismiss Signal
                </button>
              </div>
            </form>
          </section>
        )}
      </div>
    </div>
  );
}
