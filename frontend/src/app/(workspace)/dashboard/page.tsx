"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  CircleAlert,
  ClipboardList,
  Clock3,
  RefreshCw,
  ShieldCheck,
  Users,
} from "lucide-react";

import { api, ApiError, type ServiceResponse } from "@/lib/api-client";
import { useAuth } from "@/providers/auth-provider";

type PageData<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

type WorkItem = {
  id: string;
  title: string;
  description?: string | null;
  status: string;
  priority: string;
  type?: string;
  team_id: string;
  assignee_id?: string | null;
  updated_at?: string;
  created_at?: string;
};

type Approval = {
  id: string;
  work_item_id: string;
  status: string;
  approver_id?: string | null;
  requested_at?: string;
  created_at?: string;
  reason?: string | null;
};

type Team = {
  id: string;
  name: string;
  description?: string | null;
  membership_role?: string;
  role?: string;
};

type ActivityItem = {
  id: string;
  work_item_id?: string | null;
  action: string;
  actor_user_id?: string | null;
  details?: Record<string, unknown> | null;
  created_at?: string;
};

type LoadResult<T> = {
  data: T | null;
  error: unknown | null;
};

const EMPTY_PAGE: PageData<never> = {
  items: [],
  total: 0,
  limit: 5,
  offset: 0,
};

async function loadSafely<T>(
  request: Promise<ServiceResponse<T>>,
): Promise<LoadResult<T>> {
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

function formatLabel(value?: string | null): string {
  if (!value) return "Unknown";

  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatDate(value?: string): string {
  if (!value) return "Date unavailable";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Date unavailable";
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function statusStyle(status: string): string {
  switch (status) {
    case "resolved":
    case "approved":
      return "border-emerald-400/20 bg-emerald-400/[0.07] text-emerald-300";

    case "in_progress":
      return "border-blue-400/20 bg-blue-400/[0.07] text-blue-300";

    case "pending_approval":
    case "pending":
      return "border-amber-400/20 bg-amber-400/[0.07] text-amber-300";

    case "cancelled":
    case "rejected":
      return "border-red-400/20 bg-red-400/[0.07] text-red-300";

    default:
      return "border-white/[0.08] bg-white/[0.035] text-zinc-400";
  }
}

function priorityStyle(priority: string): string {
  switch (priority) {
    case "critical":
      return "text-red-300";
    case "high":
      return "text-orange-300";
    case "medium":
      return "text-amber-300";
    default:
      return "text-zinc-400";
  }
}

function activityLabel(action: string): string {
  const labels: Record<string, string> = {
    work_item_created: "created a work item",
    work_item_updated: "updated a work item",
    work_item_claimed: "claimed a work item",
    work_item_assigned: "changed work ownership",
    work_item_status_changed: "changed work status",
    work_item_priority_changed: "changed work priority",
    approval_requested: "requested approval",
    approval_approved: "approved a request",
    approval_rejected: "rejected a request",
    note_added: "added a progress note",
  };

  return labels[action] ?? formatLabel(action);
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return "The API could not be reached. Check your backend connection.";
    }

    return error.message;
  }

  return "Some workspace information could not be loaded.";
}

export default function DashboardPage() {
  const { user } = useAuth();

  const [workItems, setWorkItems] = useState<WorkItem[]>([]);
  const [workTotal, setWorkTotal] = useState(0);

  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [approvalTotal, setApprovalTotal] = useState(0);

  const [teams, setTeams] = useState<Team[]>([]);
  const [teamTotal, setTeamTotal] = useState(0);

  const [activities, setActivities] = useState<ActivityItem[]>([]);

  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function loadDashboard(isMounted: () => boolean) {
    setIsLoading(true);
    setLoadError(null);

    const [work, approvalsResult, teamsResult, activityResult] =
      await Promise.all([
        loadSafely(
          api.get<PageData<WorkItem>>("work-items/mine", {
            query: { limit: 5, offset: 0 },
          }),
        ),

        loadSafely(
          api.get<PageData<Approval>>("approvals/pending", {
            query: { limit: 5, offset: 0 },
          }),
        ),

        loadSafely(
          api.get<PageData<Team>>("users/me/teams", {
            query: { limit: 5, offset: 0 },
          }),
        ),

        loadSafely(
          api.get<PageData<ActivityItem>>("users/me/activity", {
            query: { limit: 5, offset: 0 },
          }),
        ),
      ]);

    if (!isMounted()) return;

    const allResults = [
      work,
      approvalsResult,
      teamsResult,
      activityResult,
    ];

    const failedCount = allResults.filter(
      (result) => result.error !== null,
    ).length;

    const workData = work.data ?? EMPTY_PAGE;
    const approvalData = approvalsResult.data ?? EMPTY_PAGE;
    const teamData = teamsResult.data ?? EMPTY_PAGE;
    const activityData = activityResult.data ?? EMPTY_PAGE;

    setWorkItems([...workData.items]);
    setWorkTotal(workData.total);

    setApprovals([...approvalData.items]);
    setApprovalTotal(approvalData.total);

    setTeams([...teamData.items]);
    setTeamTotal(teamData.total);

    setActivities([...activityData.items]);

    if (failedCount === allResults.length) {
      setLoadError(
        "We could not load your dashboard. Check the API connection and try again.",
      );
    } else if (failedCount > 0) {
      const failedMessages = allResults
        .filter((result) => result.error !== null)
        .map((result) => getErrorMessage(result.error));

      setLoadError(
        `Some dashboard sections could not load. ${failedMessages[0]}`,
      );
    }

    setIsLoading(false);
  }

  useEffect(() => {
    let mounted = true;

    void loadDashboard(() => mounted);

    return () => {
      mounted = false;
    };
    // Dashboard data is intentionally loaded on mount.
    // Refreshes use the same shared API client.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeWorkItems = workItems.filter(
    (item) => !["resolved", "cancelled"].includes(item.status),
  );

  const urgentWorkItems = workItems.filter(
    (item) =>
      ["high", "critical"].includes(item.priority) &&
      !["resolved", "cancelled"].includes(item.status),
  );

  const stats = [
    {
      label: "My active work",
      value: isLoading ? "—" : String(activeWorkItems.length),
      icon: ClipboardList,
      description: `${workTotal} assigned item${workTotal === 1 ? "" : "s"} in total`,
      iconClass: "text-blue-300 bg-blue-400/[0.08]",
    },
    {
      label: "High-priority work",
      value: isLoading ? "—" : String(urgentWorkItems.length),
      icon: CircleAlert,
      description: "High or critical among loaded items",
      iconClass: "text-orange-300 bg-orange-400/[0.08]",
    },
    {
      label: "Pending approvals",
      value: isLoading ? "—" : String(approvalTotal),
      icon: ShieldCheck,
      description: "Available in your approval queue",
      iconClass: "text-amber-300 bg-amber-400/[0.08]",
    },
    {
      label: "My teams",
      value: isLoading ? "—" : String(teamTotal),
      icon: Users,
      description: "Teams you belong to",
      iconClass: "text-indigo-300 bg-indigo-400/[0.08]",
    },
  ];

  return (
    <div className="mx-auto max-w-[1600px] space-y-7">
      {/* Heading */}
      <section className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 flex items-center gap-2 text-xs text-zinc-500">
            <span>Workspace</span>
            <span className="text-zinc-700">/</span>
            <span className="text-zinc-300">Overview</span>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight text-zinc-100 sm:text-3xl">
            Good to see you, {user?.full_name?.split(" ")[0] || "there"}.
          </h1>

          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
            Here&apos;s what is happening across your work and approvals.
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => {
              void loadDashboard(() => true);
            }}
            disabled={isLoading}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/[0.09] bg-white/[0.025] px-3.5 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.06] disabled:opacity-50"
          >
            <RefreshCw
              size={14}
              className={isLoading ? "animate-spin" : ""}
            />
            Refresh
          </button>

          <Link
            href="/work-items"
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-100 px-3.5 text-xs font-semibold text-zinc-950 transition hover:bg-white"
          >
            <ClipboardList size={14} />
            View work
          </Link>
        </div>
      </section>

      {/* Errors */}
      {loadError && (
        <section
          role="alert"
          className="flex flex-col gap-3 rounded-xl border border-amber-400/20 bg-amber-400/[0.04] p-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-start gap-3">
            <CircleAlert
              className="mt-0.5 shrink-0 text-amber-300"
              size={18}
            />
            <p className="text-sm leading-6 text-zinc-300">{loadError}</p>
          </div>

          <button
            type="button"
            onClick={() => {
              void loadDashboard(() => true);
            }}
            disabled={isLoading}
            className="shrink-0 rounded-lg border border-white/10 px-3 py-2 text-xs font-medium text-zinc-300 hover:bg-white/[0.05] disabled:opacity-50"
          >
            Try again
          </button>
        </section>
      )}

      {/* KPI cards */}
      <section
        aria-label="Workspace summary"
        className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4"
      >
        {stats.map((stat) => {
          const Icon = stat.icon;

          return (
            <div
              key={stat.label}
              className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 transition hover:border-white/[0.12]"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-400">
                  {stat.label}
                </span>
                <div
                  className={`flex h-9 w-9 items-center justify-center rounded-lg ${stat.iconClass}`}
                >
                  <Icon size={17} />
                </div>
              </div>

              <p className="mt-5 text-3xl font-semibold tracking-tight text-zinc-100">
                {stat.value}
              </p>

              <p className="mt-2 text-[11px] leading-5 text-zinc-500">
                {stat.description}
              </p>
            </div>
          );
        })}
      </section>

      {/* Main dashboard grid */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(340px,0.85fr)]">
        {/* My work */}
        <section className="min-w-0 overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.02]">
          <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold text-zinc-100">
                My work
              </h2>
              <p className="mt-1 text-xs text-zinc-500">
                Work items assigned to you
              </p>
            </div>

            <Link
              href="/work-items"
              className="inline-flex items-center gap-1.5 text-xs text-zinc-400 transition hover:text-white"
            >
              View all <ArrowRight size={13} />
            </Link>
          </div>

          {isLoading ? (
            <div className="space-y-3 p-5" aria-label="Loading work items">
              {[1, 2, 3].map((item) => (
                <div
                  key={item}
                  className="h-[76px] animate-pulse rounded-lg bg-white/[0.035]"
                />
              ))}
            </div>
          ) : workItems.length === 0 ? (
            <div className="flex min-h-48 flex-col items-center justify-center px-6 text-center">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/[0.07] bg-white/[0.025]">
                <CheckCircle2 className="text-zinc-500" size={20} />
              </div>
              <p className="mt-4 text-sm font-medium text-zinc-300">
                Nothing assigned yet
              </p>
              <p className="mt-1 text-xs leading-5 text-zinc-500">
                Assigned work items will appear here.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-white/[0.055]">
              {workItems.map((item) => (
                <Link
                  key={item.id}
                  href={`/work-items/${item.id}`}
                  className="group flex gap-3 px-5 py-4 transition hover:bg-white/[0.025] sm:gap-4"
                >
                  <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/[0.07] bg-white/[0.025]">
                    <ClipboardList size={15} className="text-zinc-400" />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start">
                      <p className="line-clamp-2 text-sm font-medium text-zinc-200 transition group-hover:text-white">
                        {item.title}
                      </p>

                      <span
                        className={`w-fit shrink-0 rounded-md border px-2 py-1 text-[10px] font-medium ${statusStyle(item.status)}`}
                      >
                        {formatLabel(item.status)}
                      </span>
                    </div>

                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-[11px] text-zinc-500">
                      <span className={priorityStyle(item.priority)}>
                        {formatLabel(item.priority)} priority
                      </span>
                      <span className="text-zinc-700">•</span>
                      <span>{formatLabel(item.type)}</span>
                      <span className="text-zinc-700">•</span>
                      <span>Updated {formatDate(item.updated_at)}</span>
                    </div>
                  </div>

                  <ArrowUpRight
                    size={15}
                    className="mt-1 shrink-0 text-zinc-600 transition group-hover:text-zinc-300"
                  />
                </Link>
              ))}
            </div>
          )}

          {!isLoading && workItems.length > 0 && (
            <div className="border-t border-white/[0.07] px-5 py-3">
              <p className="text-[11px] text-zinc-500">
                Showing {workItems.length} of {workTotal} assigned items
              </p>
            </div>
          )}
        </section>

        {/* Pending approvals */}
        <section className="min-w-0 overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.02]">
          <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold text-zinc-100">
                Pending approvals
              </h2>
              <p className="mt-1 text-xs text-zinc-500">
                Requests awaiting your decision
              </p>
            </div>

            <Link
              href="/approvals"
              className="inline-flex items-center gap-1.5 text-xs text-zinc-400 transition hover:text-white"
            >
              View all <ArrowRight size={13} />
            </Link>
          </div>

          {isLoading ? (
            <div className="space-y-3 p-5">
              {[1, 2, 3].map((item) => (
                <div
                  key={item}
                  className="h-[65px] animate-pulse rounded-lg bg-white/[0.035]"
                />
              ))}
            </div>
          ) : approvals.length === 0 ? (
            <div className="flex min-h-48 flex-col items-center justify-center px-6 text-center">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/[0.07] bg-white/[0.025]">
                <ShieldCheck className="text-zinc-500" size={20} />
              </div>
              <p className="mt-4 text-sm font-medium text-zinc-300">
                No pending approvals
              </p>
              <p className="mt-1 text-xs leading-5 text-zinc-500">
                New requests requiring your review will appear here.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-white/[0.055]">
              {approvals.map((approval) => (
                <Link
                  key={approval.id}
                  href={`/approvals/${approval.id}`}
                  className="group flex items-start gap-3 px-5 py-4 transition hover:bg-white/[0.025]"
                >
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-amber-400/10 bg-amber-400/[0.05]">
                    <Clock3 size={15} className="text-amber-300" />
                  </div>

                  <div className="min-w-0 flex-1">
                    <p className="break-words text-sm font-medium text-zinc-200 group-hover:text-white">
                      Approval request
                    </p>

                    <p className="mt-1 text-[11px] text-zinc-500">
                      {approval.work_item_id
                        ? `Work item ${approval.work_item_id.slice(0, 8)}`
                        : `Request ${approval.id.slice(0, 8)}`}
                    </p>

                    <p className="mt-1.5 text-[10px] text-zinc-600">
                      {formatDate(
                        approval.requested_at ?? approval.created_at,
                      )}
                    </p>
                  </div>

                  <span
                    className={`shrink-0 rounded-md border px-2 py-1 text-[10px] ${statusStyle(approval.status)}`}
                  >
                    {formatLabel(approval.status)}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Bottom dashboard grid */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        {/* Teams */}
        <section className="overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.02]">
          <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold text-zinc-100">
                Your teams
              </h2>
              <p className="mt-1 text-xs text-zinc-500">
                Teams where you have membership
              </p>
            </div>

            <Link
              href="/teams"
              className="inline-flex items-center gap-1.5 text-xs text-zinc-400 transition hover:text-white"
            >
              Manage teams <ArrowRight size={13} />
            </Link>
          </div>

          {isLoading ? (
            <div className="space-y-3 p-5">
              {[1, 2].map((item) => (
                <div
                  key={item}
                  className="h-16 animate-pulse rounded-lg bg-white/[0.035]"
                />
              ))}
            </div>
          ) : teams.length === 0 ? (
            <div className="flex min-h-36 flex-col items-center justify-center px-6 text-center">
              <Users size={22} className="text-zinc-500" />
              <p className="mt-3 text-sm font-medium text-zinc-300">
                No team memberships found
              </p>
              <p className="mt-1 text-xs leading-5 text-zinc-500">
                Your team memberships will appear here.
              </p>
            </div>
          ) : (
            <div className="grid gap-3 p-4 sm:grid-cols-2">
              {teams.map((team) => (
                <Link
                  href={`/teams/${team.id}`}
                  key={team.id}
                  className="rounded-lg border border-white/[0.07] bg-white/[0.015] p-4 transition hover:border-white/[0.14] hover:bg-white/[0.035]"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-indigo-400/10 bg-indigo-400/[0.07]">
                      <Users size={16} className="text-indigo-300" />
                    </div>

                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-zinc-200">
                        {team.name}
                      </p>
                      <p className="mt-1 text-[10px] text-zinc-500">
                        {formatLabel(
                          team.membership_role ?? team.role ?? "member",
                        )}
                      </p>
                    </div>
                  </div>

                  {team.description && (
                    <p className="mt-3 line-clamp-2 text-xs leading-5 text-zinc-500">
                      {team.description}
                    </p>
                  )}
                </Link>
              ))}
            </div>
          )}

          {!isLoading && teams.length > 0 && (
            <div className="border-t border-white/[0.07] px-5 py-3">
              <p className="text-[11px] text-zinc-500">
                Showing {teams.length} of {teamTotal} teams
              </p>
            </div>
          )}
        </section>

        {/* Recent activity */}
        <section className="overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.02]">
          <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold text-zinc-100">
                Recent activity
              </h2>
              <p className="mt-1 text-xs text-zinc-500">
                The latest actions associated with your account
              </p>
            </div>

            <Link
              href="/activity"
              className="inline-flex items-center gap-1.5 text-xs text-zinc-400 transition hover:text-white"
            >
              Activity feed <ArrowRight size={13} />
            </Link>
          </div>

          {isLoading ? (
            <div className="space-y-4 p-5">
              {[1, 2, 3].map((item) => (
                <div
                  key={item}
                  className="h-12 animate-pulse rounded-lg bg-white/[0.035]"
                />
              ))}
            </div>
          ) : activities.length === 0 ? (
            <div className="flex min-h-36 flex-col items-center justify-center px-6 text-center">
              <Activity size={22} className="text-zinc-500" />
              <p className="mt-3 text-sm font-medium text-zinc-300">
                No recent activity
              </p>
              <p className="mt-1 text-xs leading-5 text-zinc-500">
                Important actions will appear here as you work.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-white/[0.055]">
              {activities.map((activity) => (
                <div
                  key={activity.id}
                  className="flex gap-3 px-5 py-4"
                >
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/[0.07] bg-white/[0.025]">
                    <Activity size={15} className="text-zinc-400" />
                  </div>

                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-5 text-zinc-300">
                      {activityLabel(activity.action)}
                    </p>

                    <p className="mt-1 text-[11px] text-zinc-500">
                      {activity.work_item_id
                        ? `Work item ${activity.work_item_id.slice(0, 8)}`
                        : "Account activity"}
                    </p>

                    <p className="mt-1.5 text-[10px] text-zinc-600">
                      {formatDate(activity.created_at)}
                    </p>
                  </div>

                  {activity.work_item_id && (
                    <Link
                      href={`/work-items/${activity.work_item_id}`}
                      aria-label="View related work item"
                      className="mt-1 text-zinc-600 transition hover:text-zinc-200"
                    >
                      <ArrowUpRight size={15} />
                    </Link>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Footer note */}
      <div className="flex items-start gap-2 border-t border-white/[0.06] pt-4 text-[11px] leading-5 text-zinc-600">
        <ArrowDownRight size={14} className="mt-0.5 shrink-0" />
        Dashboard values reflect the returned API pages. Lists are paginated
        independently; counts derived from the five displayed work items are
        not global counts.
      </div>
    </div>
  );
}