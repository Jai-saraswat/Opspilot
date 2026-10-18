"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  Clock3,
  FileCheck2,
  LoaderCircle,
  MessageSquare,
  RefreshCw,
  Search,
  ShieldCheck,
  X,
  XCircle,
} from "lucide-react";

import { api, ApiError, type ServiceResponse } from "@/lib/api-client";
import { useAuth } from "@/providers/auth-provider";

const PAGE_SIZE = 10;

type ApprovalStatus = "pending" | "approved" | "rejected";
type ApprovalTab = "assigned" | "mine";
type Decision = "approved" | "rejected";
type RequestStatusFilter = "all" | ApprovalStatus;

interface Approval {
  id: string;
  work_item_id: string;
  requested_by: string;
  approver_id: string | null;
  status: ApprovalStatus;
  decision_reason: string | null;
  requested_at: string;
  decided_at: string | null;
  work_item_title?: string;
  work_item_priority?: string;
  requester_name?: string;
  approver_name?: string | null;
  team_id?: string;
}

interface Team {
  id: string;
  name: string;
  description?: string | null;
}

interface PageData<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

interface ReviewDialog {
  approval: Approval;
  decision: Decision;
}

function label(value?: string | null): string {
  if (!value) return "Unknown";

  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value?: string | null): string {
  if (!value) return "—";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function statusClasses(status: string): string {
  switch (status) {
    case "pending":
      return "border-amber-400/20 bg-amber-400/[0.06] text-amber-200";
    case "approved":
      return "border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-300";
    case "rejected":
      return "border-red-400/20 bg-red-400/[0.06] text-red-300";
    default:
      return "border-white/[0.08] bg-white/[0.03] text-zinc-400";
  }
}

function priorityClasses(priority?: string): string {
  switch (priority) {
    case "critical":
      return "border-red-400/20 bg-red-400/[0.06] text-red-300";
    case "high":
      return "border-orange-400/20 bg-orange-400/[0.06] text-orange-300";
    case "medium":
      return "border-amber-400/20 bg-amber-400/[0.06] text-amber-300";
    case "low":
      return "border-white/[0.08] bg-white/[0.03] text-zinc-400";
    default:
      return "border-white/[0.08] bg-white/[0.03] text-zinc-400";
  }
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return "Unable to reach the API. Check that the backend is running.";
    }

    if (error.status === 401) {
      return "Your session could not be verified. Please sign in again.";
    }

    if (error.status === 403) {
      return "You do not have permission to perform this action.";
    }

    if (error.status === 409) {
      return (
        error.message ||
        "The approval request has changed. Refresh the queue and try again."
      );
    }

    return error.message;
  }

  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}

async function loadSafely<T>(
  request: Promise<ServiceResponse<T>>,
): Promise<{ data: T | null; error: unknown | null }> {
  try {
    const response = await request;

    return {
      data: response.outputs.data,
      error: null,
    };
  } catch (error) {
    return {
      data: null,
      error,
    };
  }
}

export default function ApprovalsPage() {
  const { user } = useAuth();

  const [tab, setTab] = useState<ApprovalTab>("assigned");
  const [requestStatus, setRequestStatus] =
    useState<RequestStatusFilter>("all");

  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");

  const [isLoading, setIsLoading] = useState(true);
  const [isReviewing, setIsReviewing] = useState(false);
  const [isRetrying, setIsRetrying] = useState<string | null>(null);

  const [reviewDialog, setReviewDialog] =
    useState<ReviewDialog | null>(null);
  const [decisionReason, setDecisionReason] = useState("");

  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");

  const requestSequence = useRef(0);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const teamNames = useMemo(
    () => Object.fromEntries(teams.map((team) => [team.id, team.name])),
    [teams],
  );

  const filteredApprovals = useMemo(() => {
    const query = search.trim().toLowerCase();

    return approvals.filter((approval) => {
      const teamName = teamNames[approval.team_id ?? ""] ?? "";

      const matchesSearch =
        !query ||
        (approval.work_item_title ?? "").toLowerCase().includes(query) ||
        (approval.requester_name ?? user?.full_name ?? "")
          .toLowerCase()
          .includes(query) ||
        (approval.approver_name ?? "").toLowerCase().includes(query) ||
        teamName.toLowerCase().includes(query);

      const matchesPriority =
        !priorityFilter ||
        approval.work_item_priority === priorityFilter;

      return matchesSearch && matchesPriority;
    });
  }, [approvals, search, priorityFilter, teamNames, user?.full_name]);

  const highPriorityCount = approvals.filter((approval) =>
    ["high", "critical"].includes(approval.work_item_priority ?? ""),
  ).length;

  const loadQueue = useCallback(async () => {
    const sequence = ++requestSequence.current;

    const query = {
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
      ...(tab === "mine" && requestStatus !== "all"
        ? { status: requestStatus }
        : {}),
    };

    const approvalPath =
      tab === "assigned" ? "approvals/pending" : "approvals/requests";

    try {
      const [approvalResult, teamResult] = await Promise.all([
        loadSafely(api.get<PageData<Approval>>(approvalPath, { query })),
        loadSafely(
          api.get<PageData<Team>>("users/me/teams", {
            query: { limit: 100, offset: 0 },
          }),
        ),
      ]);

      if (sequence !== requestSequence.current) return;

      if (approvalResult.error) {
        throw approvalResult.error;
      }

      const data = approvalResult.data;

      if (!data) {
        throw new Error("The approvals response did not contain data.");
      }

      setApprovals(data.items);
      setTotal(data.total);
      setLoadError("");

      if (teamResult.data) {
        setTeams(teamResult.data.items);
      } else {
        setTeams([]);
      }
    } catch (error) {
      if (sequence !== requestSequence.current) return;

      setLoadError(getErrorMessage(error));
      setApprovals([]);
      setTotal(0);
    } finally {
      if (sequence === requestSequence.current) {
        setIsLoading(false);
      }
    }
  }, [tab, requestStatus, page]);

  useEffect(() => {
    void loadQueue();

    return () => {
      requestSequence.current += 1;
    };
  }, [loadQueue]);

  function changeTab(nextTab: ApprovalTab) {
    setIsLoading(true);
    setLoadError("");
    setActionError("");
    setNotice("");
    setTab(nextTab);
    setPage(0);
    setSearch("");
    setSearchInput("");
    setPriorityFilter("");
  }

  function refreshQueue() {
    setIsLoading(true);
    setLoadError("");
    setActionError("");
    setNotice("");
    void loadQueue();
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(searchInput.trim());
  }

  function changeRequestStatus(value: RequestStatusFilter) {
    setIsLoading(true);
    setRequestStatus(value);
    setPage(0);
    setSearch("");
    setSearchInput("");
  }

  function openReviewDialog(
    approval: Approval,
    decision: Decision,
  ) {
    setActionError("");
    setDecisionReason("");
    setReviewDialog({ approval, decision });
  }

  async function submitDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!reviewDialog || isReviewing) return;

    const { approval, decision } = reviewDialog;

    setIsReviewing(true);
    setActionError("");
    setNotice("");

    try {
      await api.post(
        `approvals/${encodeURIComponent(approval.id)}/decision`,
        {
          decision,
          decision_reason: decisionReason.trim() || null,
        },
      );

      setReviewDialog(null);
      setDecisionReason("");

      setNotice(
        decision === "approved"
          ? "Approval recorded. The associated work item was resolved by the workflow."
          : "Request rejected. The associated work item was returned to in-progress.",
      );

      setIsLoading(true);
      await loadQueue();
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setIsReviewing(false);
    }
  }

  async function retryApproval(approval: Approval) {
    if (isRetrying) return;

    setIsRetrying(approval.id);
    setActionError("");
    setNotice("");

    try {
      await api.post(
        `approvals/${encodeURIComponent(approval.id)}/retry`,
        {},
      );

      setNotice(
        "Approval request resubmitted. It will appear in the assigned approver's queue once the request is assigned.",
      );

      setIsLoading(true);
      await loadQueue();
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setIsRetrying(null);
    }
  }

  const firstItem = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const lastItem = Math.min((page + 1) * PAGE_SIZE, total);

  return (
    <div className="mx-auto max-w-[1500px] space-y-7">
      {/* Header */}
      <section className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 flex items-center gap-2 text-xs text-zinc-500">
            <span>Workspace</span>
            <span className="text-zinc-700">/</span>
            <span className="text-zinc-300">Approvals</span>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Approvals
          </h1>

          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
            Review requests assigned to you or track approval requests you
            have submitted.
          </p>
        </div>

        <button
          type="button"
          onClick={refreshQueue}
          disabled={isLoading || isReviewing || Boolean(isRetrying)}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/[0.08] px-4 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.04] disabled:opacity-50"
        >
          <RefreshCw
            size={14}
            className={isLoading ? "animate-spin" : ""}
          />
          Refresh
        </button>
      </section>

      {notice && (
        <div
          role="status"
          className="flex items-start gap-3 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.05] px-4 py-3"
        >
          <CheckCircle2
            size={17}
            className="mt-0.5 shrink-0 text-emerald-300"
          />
          <p className="flex-1 text-sm leading-6 text-emerald-200">
            {notice}
          </p>
          <button
            type="button"
            onClick={() => setNotice("")}
            aria-label="Dismiss notification"
            className="text-emerald-300/70 hover:text-emerald-200"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {actionError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-xl border border-red-400/20 bg-red-400/[0.04] px-4 py-3"
        >
          <AlertCircle
            size={17}
            className="mt-0.5 shrink-0 text-red-300"
          />
          <p className="flex-1 text-sm leading-6 text-red-200">
            {actionError}
          </p>
          <button
            type="button"
            onClick={() => setActionError("")}
            aria-label="Dismiss error"
            className="text-red-300/70 hover:text-red-200"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {/* Summary */}
      <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-zinc-400">
              {tab === "assigned" ? "Assigned to me" : "My requests"}
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-400/[0.08] text-indigo-300">
              <FileCheck2 size={17} />
            </div>
          </div>

          <p className="mt-5 text-3xl font-semibold tracking-tight">
            {isLoading ? "—" : total}
          </p>

          <p className="mt-2 text-[11px] text-zinc-500">
            {tab === "assigned"
              ? "Eligible pending requests assigned to you"
              : requestStatus === "all"
                ? "All requests you have submitted"
                : `${label(requestStatus)} requests you submitted`}
          </p>
        </div>

        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-zinc-400">
              High and critical
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-red-400/[0.08] text-red-300">
              <AlertCircle size={17} />
            </div>
          </div>

          <p className="mt-5 text-3xl font-semibold tracking-tight">
            {isLoading ? "—" : highPriorityCount}
          </p>

          <p className="mt-2 text-[11px] text-zinc-500">
            In the currently loaded page
          </p>
        </div>

        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-zinc-400">
              Decision integrity
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-400/[0.08] text-emerald-300">
              <ShieldCheck size={17} />
            </div>
          </div>

          <p className="mt-5 text-sm font-semibold text-zinc-100">
            Server enforced
          </p>

          <p className="mt-2 text-[11px] leading-5 text-zinc-500">
            The backend validates approver eligibility and request state.
          </p>
        </div>
      </section>

      {/* Tabs */}
      <section className="flex flex-col justify-between gap-4 border-b border-white/[0.07] pb-4 sm:flex-row sm:items-center">
        <div className="inline-flex w-fit rounded-lg border border-white/[0.08] bg-white/[0.02] p-1">
          <button
            type="button"
            onClick={() => changeTab("assigned")}
            className={[
              "rounded-md px-4 py-2.5 text-xs font-medium transition",
              tab === "assigned"
                ? "bg-white/[0.09] text-white"
                : "text-zinc-500 hover:text-zinc-200",
            ].join(" ")}
          >
            Assigned to me
          </button>

          <button
            type="button"
            onClick={() => changeTab("mine")}
            className={[
              "rounded-md px-4 py-2.5 text-xs font-medium transition",
              tab === "mine"
                ? "bg-white/[0.09] text-white"
                : "text-zinc-500 hover:text-zinc-200",
            ].join(" ")}
          >
            My requests
          </button>
        </div>

        {tab === "mine" && (
          <div className="relative min-w-0 sm:w-48">
            <select
              value={requestStatus}
              onChange={(event) =>
                changeRequestStatus(
                  event.target.value as RequestStatusFilter,
                )
              }
              aria-label="Filter my approval requests by status"
              className="h-10 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#111114] pl-3 pr-9 text-xs text-zinc-300 outline-none focus:border-indigo-400/50"
            >
              <option value="all">All request statuses</option>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>

            <ChevronDown
              size={14}
              className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
            />
          </div>
        )}
      </section>

      {/* Search and priority filter */}
      <section className="space-y-3">
        <form
          onSubmit={submitSearch}
          className="flex flex-col gap-2 sm:flex-row"
        >
          <div className="relative min-w-0 flex-1">
            <Search
              size={16}
              className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-500"
            />
            <input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Search by work item, requester, or team..."
              aria-label="Search the current approval page"
              className="h-11 w-full rounded-lg border border-white/[0.08] bg-white/[0.02] pl-10 pr-4 text-sm text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-indigo-400/50"
            />
          </div>

          <button
            type="submit"
            className="h-11 rounded-lg border border-white/[0.08] bg-white/[0.04] px-5 text-xs font-medium text-zinc-200 hover:bg-white/[0.08]"
          >
            Search
          </button>

          <div className="relative min-w-0 sm:w-44">
            <select
              value={priorityFilter}
              onChange={(event) => setPriorityFilter(event.target.value)}
              aria-label="Filter by work item priority"
              className="h-11 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#111114] pl-3 pr-9 text-xs text-zinc-300 outline-none focus:border-indigo-400/50"
            >
              <option value="">All priorities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>

            <ChevronDown
              size={14}
              className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
            />
          </div>
        </form>

        <p className="text-[11px] text-zinc-600">
          Search and priority filters apply to the currently loaded page.
          Status filtering for your requests is handled by the API.
        </p>
      </section>

      {/* Queue */}
      <section>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-100">
              {tab === "assigned"
                ? "Requests awaiting your decision"
                : "Requests you submitted"}
            </h2>

            <p className="mt-1 text-xs text-zinc-500">
              {isLoading
                ? "Loading approval requests..."
                : `${filteredApprovals.length} shown · ${total} total`}
            </p>
          </div>

          <Link
            href="/work-items"
            className="inline-flex items-center gap-2 text-xs text-zinc-400 hover:text-white"
          >
            View work items
            <ArrowRight size={14} />
          </Link>
        </div>

        <div className="overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.015]">
          {isLoading ? (
            <div className="space-y-3 p-5" aria-label="Loading approvals">
              {[1, 2, 3].map((index) => (
                <div
                  key={index}
                  className="h-36 animate-pulse rounded-xl bg-white/[0.035]"
                />
              ))}
            </div>
          ) : loadError ? (
            <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
              <AlertCircle size={25} className="text-red-300" />
              <h3 className="mt-4 text-sm font-semibold text-zinc-200">
                Could not load approval requests
              </h3>
              <p className="mt-2 max-w-md text-xs leading-5 text-zinc-500">
                {loadError}
              </p>
              <button
                type="button"
                onClick={refreshQueue}
                className="mt-5 rounded-lg border border-white/10 px-4 py-2 text-xs text-zinc-200 hover:bg-white/[0.04]"
              >
                Try again
              </button>
            </div>
          ) : filteredApprovals.length === 0 ? (
            <div className="flex min-h-72 flex-col items-center justify-center px-6 py-12 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-white/[0.07] bg-white/[0.025]">
                {search || priorityFilter ? (
                  <Search size={21} className="text-zinc-500" />
                ) : (
                  <FileCheck2 size={21} className="text-zinc-500" />
                )}
              </div>

              <h3 className="mt-4 text-sm font-medium text-zinc-200">
                {search || priorityFilter
                  ? "No matching requests"
                  : tab === "assigned"
                    ? "No requests assigned to you"
                    : "No requests submitted yet"}
              </h3>

              <p className="mt-2 max-w-md text-xs leading-5 text-zinc-500">
                {search || priorityFilter
                  ? "Try a different search or clear the priority filter."
                  : tab === "assigned"
                    ? "Only pending requests assigned to you and allowed by your team role appear in this queue. Switch to My requests to track your own submissions."
                    : "When you request approval for a work item, it will appear here with its current status and assigned approver."}
              </p>

              {(search || priorityFilter) && (
                <button
                  type="button"
                  onClick={() => {
                    setSearch("");
                    setSearchInput("");
                    setPriorityFilter("");
                  }}
                  className="mt-4 text-xs text-zinc-300 underline decoration-white/20 underline-offset-4 hover:text-white"
                >
                  Clear filters
                </button>
              )}
            </div>
          ) : (
            <div className="divide-y divide-white/[0.06]">
              {filteredApprovals.map((approval) => {
                const teamName = teamNames[approval.team_id ?? ""];

                const requesterName =
                  tab === "mine"
                    ? user?.full_name || "You"
                    : approval.requester_name || "Team member";

                const approverName =
                  approval.approver_name ||
                  (approval.approver_id && tab === "assigned"
                    ? user?.full_name || "Assigned reviewer"
                    : null);

                return (
                  <article
                    key={approval.id}
                    className="p-5 transition hover:bg-white/[0.015] sm:p-6"
                  >
                    <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-start">
                      <div className="min-w-0 flex-1">
                        <div className="mb-3 flex flex-wrap items-center gap-2">
                          <span
                            className={`rounded-md border px-2.5 py-1 text-[10px] font-medium ${statusClasses(approval.status)}`}
                          >
                            {label(approval.status)}
                          </span>

                          <span
                            className={`rounded-md border px-2.5 py-1 text-[10px] font-medium ${priorityClasses(approval.work_item_priority)}`}
                          >
                            {label(approval.work_item_priority ?? "unknown")} priority
                          </span>

                          {teamName && (
                            <span className="rounded-md border border-white/[0.07] px-2.5 py-1 text-[10px] text-zinc-400">
                              {teamName}
                            </span>
                          )}
                        </div>

                        <h3 className="break-words text-base font-semibold text-zinc-100">
                          {approval.work_item_title || "Untitled work item"}
                        </h3>

                        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-zinc-400">
                          <span>
                            <span className="text-zinc-600">
                              Requested by{" "}
                            </span>
                            <span className="text-zinc-200">
                              {requesterName}
                            </span>
                          </span>

                          <span>
                            <span className="text-zinc-600">Approver </span>
                            <span className="text-zinc-200">
                              {approverName ||
                                (approval.status === "pending"
                                  ? "Not assigned"
                                  : "Unavailable")}
                            </span>
                          </span>
                        </div>

                        <p className="mt-3 flex items-center gap-2 text-[11px] text-zinc-500">
                          <Clock3 size={12} />
                          Requested {formatDate(approval.requested_at)}
                        </p>

                        {approval.decided_at && (
                          <p className="mt-2 text-[11px] text-zinc-500">
                            Decided {formatDate(approval.decided_at)}
                          </p>
                        )}

                        {approval.decision_reason && (
                          <div className="mt-4 rounded-lg border border-white/[0.06] bg-white/[0.015] p-3">
                            <p className="mb-1 flex items-center gap-2 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
                              <MessageSquare size={12} />
                              Decision note
                            </p>
                            <p className="whitespace-pre-wrap text-xs leading-5 text-zinc-400">
                              {approval.decision_reason}
                            </p>
                          </div>
                        )}

                        {tab === "mine" &&
                          approval.status === "pending" &&
                          !approval.approver_id && (
                            <p className="mt-4 rounded-lg border border-amber-400/15 bg-amber-400/[0.035] p-3 text-xs leading-5 text-amber-200/80">
                              This request is waiting for an approver to be
                              assigned. It will not appear in an individual
                              reviewer&apos;s queue until assigned.
                            </p>
                          )}
                      </div>

                      <div className="flex shrink-0 flex-col gap-2 sm:flex-row xl:w-48 xl:flex-col">
                        <Link
                          href={`/work-items/${encodeURIComponent(approval.work_item_id)}`}
                          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.04] hover:text-white"
                        >
                          View work item
                          <ArrowRight size={13} />
                        </Link>

                        {tab === "assigned" &&
                          approval.status === "pending" && (
                            <>
                              <button
                                type="button"
                                onClick={() =>
                                  openReviewDialog(approval, "approved")
                                }
                                disabled={isReviewing || Boolean(isRetrying)}
                                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-emerald-400 px-3 text-xs font-semibold text-zinc-950 transition hover:bg-emerald-300 disabled:opacity-50"
                              >
                                <CheckCircle2 size={14} />
                                Approve
                              </button>

                              <button
                                type="button"
                                onClick={() =>
                                  openReviewDialog(approval, "rejected")
                                }
                                disabled={isReviewing || Boolean(isRetrying)}
                                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-red-400/20 bg-red-400/[0.04] px-3 text-xs font-medium text-red-300 transition hover:bg-red-400/[0.09] disabled:opacity-50"
                              >
                                <XCircle size={14} />
                                Reject
                              </button>
                            </>
                          )}

                        {tab === "mine" &&
                          approval.status === "rejected" && (
                            <button
                              type="button"
                              onClick={() => void retryApproval(approval)}
                              disabled={
                                isReviewing ||
                                Boolean(isRetrying) ||
                                isLoading
                              }
                              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-indigo-400/20 bg-indigo-400/[0.05] px-3 text-xs font-medium text-indigo-200 transition hover:bg-indigo-400/[0.1] disabled:opacity-50"
                            >
                              {isRetrying === approval.id ? (
                                <LoaderCircle
                                  size={14}
                                  className="animate-spin"
                                />
                              ) : (
                                <RefreshCw size={14} />
                              )}
                              Retry request
                            </button>
                          )}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          {!isLoading && !loadError && total > 0 && (
            <div className="flex flex-col gap-3 border-t border-white/[0.07] px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-[11px] text-zinc-500">
                Showing{" "}
                <span className="text-zinc-300">
                  {firstItem}–{lastItem}
                </span>{" "}
                of <span className="text-zinc-300">{total}</span>
              </p>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={page === 0}
                  onClick={() => {
                    setIsLoading(true);
                    setPage((current) => Math.max(0, current - 1));
                  }}
                  className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs text-zinc-300 hover:bg-white/[0.04] disabled:opacity-35"
                >
                  Previous
                </button>

                <span className="px-2 text-[11px] text-zinc-500">
                  {page + 1} / {totalPages}
                </span>

                <button
                  type="button"
                  disabled={page + 1 >= totalPages}
                  onClick={() => {
                    setIsLoading(true);
                    setPage((current) =>
                      Math.min(totalPages - 1, current + 1),
                    );
                  }}
                  className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs text-zinc-300 hover:bg-white/[0.04] disabled:opacity-35"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Decision dialog */}
      {reviewDialog && (
        <div
          className="fixed inset-0 z-[100] flex items-end justify-center bg-black/75 p-0 backdrop-blur-sm sm:items-center sm:p-5"
          onMouseDown={(event) => {
            if (
              event.target === event.currentTarget &&
              !isReviewing
            ) {
              setReviewDialog(null);
            }
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="review-approval-title"
            className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-2xl border border-white/[0.09] bg-[#111114] p-5 shadow-2xl shadow-black/50 sm:rounded-2xl sm:p-7"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.17em] text-zinc-500">
                  Approval decision
                </p>

                <h2
                  id="review-approval-title"
                  className="mt-2 text-xl font-semibold text-zinc-100"
                >
                  {reviewDialog.decision === "approved"
                    ? "Approve this request?"
                    : "Reject this request?"}
                </h2>

                <p className="mt-2 text-sm leading-6 text-zinc-400">
                  {reviewDialog.approval.work_item_title ||
                    "Untitled work item"}
                </p>
              </div>

              <button
                type="button"
                onClick={() => setReviewDialog(null)}
                disabled={isReviewing}
                aria-label="Close dialog"
                className="rounded-lg p-2 text-zinc-500 hover:bg-white/[0.05] hover:text-white disabled:opacity-50"
              >
                <X size={18} />
              </button>
            </div>

            <div
              className={[
                "mt-5 rounded-lg border p-3 text-xs leading-5",
                reviewDialog.decision === "approved"
                  ? "border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-200"
                  : "border-red-400/20 bg-red-400/[0.05] text-red-200",
              ].join(" ")}
            >
              {reviewDialog.decision === "approved"
                ? "The backend will validate this decision and resolve the associated work item if the approval succeeds."
                : "The backend will validate the rejection and update the work item as part of the workflow."}
            </div>

            <form onSubmit={submitDecision} className="mt-5 space-y-4">
              <div className="space-y-2">
                <label
                  htmlFor="decision-reason"
                  className="flex items-center gap-2 text-xs font-medium text-zinc-300"
                >
                  <MessageSquare size={14} className="text-zinc-500" />
                  Decision note
                  <span className="font-normal text-zinc-600">
                    (optional)
                  </span>
                </label>

                <textarea
                  id="decision-reason"
                  value={decisionReason}
                  onChange={(event) =>
                    setDecisionReason(event.target.value)
                  }
                  maxLength={2000}
                  rows={4}
                  disabled={isReviewing}
                  placeholder={
                    reviewDialog.decision === "approved"
                      ? "Add context for the approval..."
                      : "Explain why this request is being rejected..."
                  }
                  className="w-full resize-y rounded-lg border border-white/[0.08] bg-white/[0.025] px-3.5 py-3 text-sm leading-6 text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-indigo-400/50 disabled:opacity-50"
                />

                <p className="text-right text-[10px] text-zinc-600">
                  {decisionReason.length}/2000
                </p>
              </div>

              {actionError && (
                <p
                  role="alert"
                  className="rounded-lg border border-red-400/20 bg-red-400/[0.05] p-3 text-xs leading-5 text-red-300"
                >
                  {actionError}
                </p>
              )}

              <div className="flex flex-col-reverse gap-2 border-t border-white/[0.07] pt-4 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  onClick={() => setReviewDialog(null)}
                  disabled={isReviewing}
                  className="h-10 rounded-lg border border-white/[0.08] px-4 text-xs font-medium text-zinc-300 hover:bg-white/[0.04] disabled:opacity-50"
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  disabled={isReviewing || decisionReason.length > 2000}
                  className={[
                    "inline-flex h-10 items-center justify-center gap-2 rounded-lg px-4 text-xs font-semibold transition disabled:opacity-50",
                    reviewDialog.decision === "approved"
                      ? "bg-emerald-400 text-zinc-950 hover:bg-emerald-300"
                      : "bg-red-400 text-zinc-950 hover:bg-red-300",
                  ].join(" ")}
                >
                  {isReviewing ? (
                    <>
                      <LoaderCircle size={14} className="animate-spin" />
                      Recording decision...
                    </>
                  ) : reviewDialog.decision === "approved" ? (
                    <>
                      <CheckCircle2 size={14} />
                      Confirm approval
                    </>
                  ) : (
                    <>
                      <XCircle size={14} />
                      Confirm rejection
                    </>
                  )}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}