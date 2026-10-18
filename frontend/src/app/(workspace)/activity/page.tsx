"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity as ActivityIcon,
  AlertCircle,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  FileCheck2,
  Filter,
  Loader2,
  RefreshCw,
  Search,
  UserRound,
  Users,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { api } from "@/lib/api-client";

const PAGE_SIZE = 25;

type PageData<T> = {
  items: T[];
  total?: number;
  limit?: number;
  offset?: number;
};

type ListPayload<T> = PageData<T> | T[];

type TeamRecord = {
  id?: string;
  team_id?: string;
  name?: string;
  team_name?: string;
  description?: string | null;
  role?: string;
  membership_role?: string;
};

type TeamMember = {
  id?: string;
  user_id?: string;
  account_id?: string;
  member_id?: string;
  actor_id?: string;
  full_name?: string;
  display_name?: string;
  name?: string;
  email?: string;
  role?: string;
};

type ActivityRecord = {
  id?: string;
  work_item_id?: string | null;
  actor_id?: string | null;
  action: string;
  details?: unknown;
  created_at: string;
};

type ActionMeta = {
  label: string;
  icon: LucideIcon;
  tone: string;
};

const ACTION_META: Record<string, ActionMeta> = {
  work_item_created: {
    label: "Work item created",
    icon: CheckCircle2,
    tone: "border-emerald-500/20 bg-emerald-500/10 text-emerald-300",
  },
  work_item_updated: {
    label: "Work item updated",
    icon: ActivityIcon,
    tone: "border-blue-500/20 bg-blue-500/10 text-blue-300",
  },
  work_item_claimed: {
    label: "Work item claimed",
    icon: UserRound,
    tone: "border-violet-500/20 bg-violet-500/10 text-violet-300",
  },
  assignee_changed: {
    label: "Assignee changed",
    icon: Users,
    tone: "border-sky-500/20 bg-sky-500/10 text-sky-300",
  },
  status_changed: {
    label: "Status changed",
    icon: RefreshCw,
    tone: "border-amber-500/20 bg-amber-500/10 text-amber-300",
  },
  priority_changed: {
    label: "Priority changed",
    icon: AlertCircle,
    tone: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  },
  approval_requested: {
    label: "Approval requested",
    icon: FileCheck2,
    tone: "border-violet-500/20 bg-violet-500/10 text-violet-300",
  },
  approval_approver_assigned: {
    label: "Approver assigned",
    icon: UserRound,
    tone: "border-sky-500/20 bg-sky-500/10 text-sky-300",
  },
  approval_retried: {
    label: "Approval retried",
    icon: RefreshCw,
    tone: "border-amber-500/20 bg-amber-500/10 text-amber-300",
  },
  approval_approved: {
    label: "Approval approved",
    icon: CheckCircle2,
    tone: "border-emerald-500/20 bg-emerald-500/10 text-emerald-300",
  },
  approval_rejected: {
    label: "Approval rejected",
    icon: XCircle,
    tone: "border-red-500/20 bg-red-500/10 text-red-300",
  },
};

const ACTION_OPTIONS = [
  { value: "", label: "All activity" },
  { value: "work_item_created", label: "Work item created" },
  { value: "work_item_updated", label: "Work item updated" },
  { value: "work_item_claimed", label: "Work item claimed" },
  { value: "assignee_changed", label: "Assignee changed" },
  { value: "status_changed", label: "Status changed" },
  { value: "priority_changed", label: "Priority changed" },
  { value: "approval_requested", label: "Approval requested" },
  { value: "approval_approver_assigned", label: "Approver assigned" },
  { value: "approval_retried", label: "Approval retried" },
  { value: "approval_approved", label: "Approval approved" },
  { value: "approval_rejected", label: "Approval rejected" },
];

function getItems<T>(
  payload: ListPayload<T> | null | undefined,
): T[] {
  if (Array.isArray(payload)) {
    return payload as T[];
  }

  return (payload as PageData<T> | null | undefined)?.items ?? [];
}

function getTotal<T>(
  payload: ListPayload<T> | null | undefined,
  fallback: number,
): number {
  if (payload && !Array.isArray(payload)) {
    const total = (payload as PageData<T>).total;

    if (typeof total === "number" && Number.isFinite(total)) {
      return total;
    }
  }

  return fallback;
}

function getTeamId(team: TeamRecord): string {
  return team.id ?? team.team_id ?? "";
}

function getTeamName(team: TeamRecord): string {
  return team.name ?? team.team_name ?? "Unnamed team";
}

function getMemberId(member: TeamMember): string {
  return (
    member.user_id ??
    member.account_id ??
    member.actor_id ??
    member.member_id ??
    member.id ??
    ""
  );
}

function getMemberName(member: TeamMember): string {
  return (
    member.full_name ??
    member.display_name ??
    member.name ??
    member.email ??
    "Team member"
  );
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return "Something went wrong. Please try again.";
}

function humanize(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function getActionMeta(action: string): ActionMeta {
  return (
    ACTION_META[action] ?? {
      label: humanize(action || "Activity"),
      icon: ActivityIcon,
      tone: "border-white/10 bg-white/[0.04] text-zinc-300",
    }
  );
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Time unavailable";
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatDetailEntries(
  details: unknown,
): Array<[string, string]> {
  if (typeof details === "string") {
    const value = details.trim();

    return value ? [["Details", value]] : [];
  }

  if (
    typeof details !== "object" ||
    details === null ||
    Array.isArray(details)
  ) {
    return [];
  }

  return Object.entries(details as Record<string, unknown>)
    .filter(([key, value]) => {
      if (/(^id$|_id$|uuid|token|password)/i.test(key)) {
        return false;
      }

      return (
        value !== null &&
        value !== undefined &&
        ["string", "number", "boolean"].includes(typeof value) &&
        String(value).trim().length > 0
      );
    })
    .slice(0, 4)
    .map(([key, value]) => [
      humanize(key),
      String(value),
    ]);
}

function detailsSearchText(details: unknown): string {
  return formatDetailEntries(details)
    .map(([key, value]) => `${key} ${value}`)
    .join(" ");
}

function getActorLabel(
  actorId: string | null | undefined,
  memberMap: Map<string, TeamMember>,
): string {
  if (!actorId) {
    return "System";
  }

  const member = memberMap.get(actorId);

  return member ? getMemberName(member) : "Team member";
}

export default function ActivityPage() {
  const [teams, setTeams] = useState<TeamRecord[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState("");

  const [members, setMembers] = useState<TeamMember[]>([]);
  const [activities, setActivities] = useState<ActivityRecord[]>([]);
  const [total, setTotal] = useState(0);

  const [page, setPage] = useState(0);
  const [actionFilter, setActionFilter] = useState("");
  const [searchTerm, setSearchTerm] = useState("");

  const [isLoadingTeams, setIsLoadingTeams] = useState(true);
  const [isLoadingMembers, setIsLoadingMembers] = useState(true);
  const [isLoadingActivity, setIsLoadingActivity] = useState(true);

  const [teamError, setTeamError] = useState<string | null>(null);
  const [memberError, setMemberError] = useState<string | null>(null);
  const [activityError, setActivityError] = useState<string | null>(null);

  const [teamRefreshKey, setTeamRefreshKey] = useState(0);
  const [activityRefreshKey, setActivityRefreshKey] = useState(0);

  const selectedTeam = useMemo(
    () =>
      teams.find((team) => getTeamId(team) === selectedTeamId) ?? null,
    [teams, selectedTeamId],
  );

  const memberMap = useMemo(() => {
    const map = new Map<string, TeamMember>();

    for (const member of members) {
      const id = getMemberId(member);

      if (id) {
        map.set(id, member);
      }
    }

    return map;
  }, [members]);

  const filteredActivities = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();

    if (!query) {
      return activities;
    }

    return activities.filter((activity) => {
      const actor = getActorLabel(activity.actor_id, memberMap);
      const label = getActionMeta(activity.action).label;
      const details = detailsSearchText(activity.details);

      return `${actor} ${label} ${details}`
        .toLowerCase()
        .includes(query);
    });
  }, [activities, searchTerm, memberMap]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Load teams once, or again when the user explicitly refreshes.
  useEffect(() => {
    let cancelled = false;

    async function loadTeams() {
      try {
        const response = await api.get<ListPayload<TeamRecord>>(
          "users/me/teams",
        );

        if (cancelled) return;

        const data = response.outputs?.data ?? null;
        const nextTeams = getItems(data);

        setTeams(nextTeams);
        setTeamError(null);

        setSelectedTeamId((currentId) => {
          const stillAvailable = nextTeams.some(
            (team) => getTeamId(team) === currentId,
          );

          return stillAvailable
            ? currentId
            : getTeamId(nextTeams[0] ?? {});
        });
      } catch (error) {
        if (!cancelled) {
          setTeamError(getErrorMessage(error));
          setTeams([]);
        }
      } finally {
        if (!cancelled) {
          setIsLoadingTeams(false);
        }
      }
    }

    void loadTeams();

    return () => {
      cancelled = true;
    };
  }, [teamRefreshKey]);

  // Load team members for activity-name resolution.
  useEffect(() => {
    if (!selectedTeamId) {
      return;
    }

    let cancelled = false;

    async function loadMembers() {
      try {
        const response = await api.get<ListPayload<TeamMember>>(
          `teams/${encodeURIComponent(selectedTeamId)}/members?limit=100&offset=0`,
        );

        if (cancelled) return;

        setMembers(getItems(response.outputs?.data ?? null));
        setMemberError(null);
      } catch (error) {
        if (!cancelled) {
          setMembers([]);
          setMemberError(getErrorMessage(error));
        }
      } finally {
        if (!cancelled) {
          setIsLoadingMembers(false);
        }
      }
    }

    void loadMembers();

    return () => {
      cancelled = true;
    };
  }, [selectedTeamId]);

  // Fetch a bounded page from the server. Cancellation prevents stale
  // responses from overwriting results for a newer team/filter/page.
  useEffect(() => {
    if (!selectedTeamId) {
      return;
    }

    let cancelled = false;

    async function loadActivity() {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
      });

      if (actionFilter) {
        params.set("action", actionFilter);
      }

      try {
        const response = await api.get<ListPayload<ActivityRecord>>(
          `teams/${encodeURIComponent(selectedTeamId)}/activity?${params.toString()}`,
        );

        if (cancelled) return;

        const data = response.outputs?.data ?? null;
        const nextActivities = getItems(data);

        setActivities(nextActivities);
        setTotal(getTotal(data, nextActivities.length));
        setActivityError(null);
      } catch (error) {
        if (!cancelled) {
          setActivities([]);
          setTotal(0);
          setActivityError(getErrorMessage(error));
        }
      } finally {
        if (!cancelled) {
          setIsLoadingActivity(false);
        }
      }
    }

    void loadActivity();

    return () => {
      cancelled = true;
    };
  }, [
    selectedTeamId,
    page,
    actionFilter,
    activityRefreshKey,
  ]);

  function handleTeamChange(nextTeamId: string) {
    setSelectedTeamId(nextTeamId);
    setPage(0);
    setSearchTerm("");

    setMembers([]);
    setMemberError(null);
    setIsLoadingMembers(true);

    setActivities([]);
    setTotal(0);
    setActivityError(null);
    setIsLoadingActivity(true);
  }

  function handleActionChange(nextAction: string) {
    setActionFilter(nextAction);
    setPage(0);
    setActivityError(null);
    setIsLoadingActivity(true);
  }

  function handleRefresh() {
    setActivityError(null);
    setIsLoadingActivity(true);
    setActivityRefreshKey((current) => current + 1);
  }

  function handleTeamRefresh() {
    setTeamError(null);
    setIsLoadingTeams(true);
    setTeamRefreshKey((current) => current + 1);
  }

  function handlePreviousPage() {
    if (page > 0) {
      setIsLoadingActivity(true);
      setPage((current) => Math.max(0, current - 1));
    }
  }

  function handleNextPage() {
    if (page + 1 < totalPages) {
      setIsLoadingActivity(true);
      setPage((current) => Math.min(totalPages - 1, current + 1));
    }
  }

  return (
    <main className="min-h-screen bg-[#09090b] px-4 py-7 text-zinc-100 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-7">
        {/* Page heading */}
        <header className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">
              <ActivityIcon size={14} />
              Workspace
            </div>

            <h1 className="text-3xl font-semibold tracking-tight text-white">
              Activity
            </h1>

            <p className="max-w-2xl text-sm leading-6 text-zinc-400">
              Review team actions, ownership changes, workflow transitions,
              and approval decisions in one chronological history.
            </p>
          </div>

          <button
            type="button"
            onClick={handleRefresh}
            disabled={!selectedTeamId || isLoadingActivity}
            className="inline-flex h-10 items-center justify-center gap-2 self-start rounded-lg border border-white/10 bg-white/[0.03] px-4 text-sm font-medium text-zinc-200 transition hover:bg-white/[0.07] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw
              size={15}
              className={isLoadingActivity ? "animate-spin" : ""}
            />
            Refresh
          </button>
        </header>

        {/* Team selector and activity filters */}
        <section className="rounded-xl border border-white/[0.08] bg-[#101012] p-4 sm:p-5">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,1fr)_minmax(220px,1fr)_minmax(220px,1.2fr)]">
            <div className="space-y-2">
              <label
                htmlFor="activity-team"
                className="text-sm font-medium text-zinc-300"
              >
                Team
              </label>

              <div className="relative">
                <Users
                  size={16}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500"
                />

                <select
                  id="activity-team"
                  value={selectedTeamId}
                  onChange={(event) =>
                    handleTeamChange(event.target.value)
                  }
                  disabled={isLoadingTeams || teams.length === 0}
                  className="h-11 w-full appearance-none rounded-lg border border-white/10 bg-[#18181b] pl-9 pr-10 text-sm text-zinc-100 outline-none transition focus:border-violet-500/60 disabled:opacity-50"
                >
                  {teams.length === 0 && (
                    <option value="">
                      {isLoadingTeams ? "Loading teams..." : "No teams available"}
                    </option>
                  )}

                  {teams.map((team) => {
                    const id = getTeamId(team);

                    if (!id) return null;

                    return (
                      <option key={id} value={id}>
                        {getTeamName(team)}
                      </option>
                    );
                  })}
                </select>

                <ChevronDown
                  size={15}
                  className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
                />
              </div>
            </div>

            <div className="space-y-2">
              <label
                htmlFor="activity-action"
                className="text-sm font-medium text-zinc-300"
              >
                Event type
              </label>

              <div className="relative">
                <Filter
                  size={15}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500"
                />

                <select
                  id="activity-action"
                  value={actionFilter}
                  onChange={(event) =>
                    handleActionChange(event.target.value)
                  }
                  className="h-11 w-full appearance-none rounded-lg border border-white/10 bg-[#18181b] pl-9 pr-10 text-sm text-zinc-100 outline-none transition focus:border-violet-500/60"
                >
                  {ACTION_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>

                <ChevronDown
                  size={15}
                  className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
                />
              </div>
            </div>

            <div className="space-y-2">
              <label
                htmlFor="activity-search"
                className="text-sm font-medium text-zinc-300"
              >
                Search this page
              </label>

              <div className="relative">
                <Search
                  size={16}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500"
                />

                <input
                  id="activity-search"
                  type="search"
                  value={searchTerm}
                  onChange={(event) =>
                    setSearchTerm(event.target.value)
                  }
                  placeholder="Search actions or people..."
                  className="h-11 w-full rounded-lg border border-white/10 bg-[#18181b] pl-9 pr-3 text-sm text-zinc-100 outline-none placeholder:text-zinc-600 transition focus:border-violet-500/60"
                />
              </div>
            </div>
          </div>

          {selectedTeam && (
            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-4 text-xs text-zinc-500">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.025] px-2.5 py-1.5">
                <Users size={12} />
                {getTeamName(selectedTeam)}
              </span>

              <span className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.025] px-2.5 py-1.5">
                <ActivityIcon size={12} />
                {total} event{total === 1 ? "" : "s"}
              </span>
            </div>
          )}
        </section>

        {/* Team loading and error states */}
        {isLoadingTeams && (
          <div className="flex items-center justify-center gap-3 rounded-xl border border-white/[0.08] bg-[#101012] px-5 py-14 text-sm text-zinc-400">
            <Loader2 size={18} className="animate-spin" />
            Loading your teams...
          </div>
        )}

        {!isLoadingTeams && teamError && (
          <div className="rounded-xl border border-red-500/20 bg-red-500/[0.05] p-5">
            <div className="flex items-start gap-3">
              <AlertCircle
                size={19}
                className="mt-0.5 shrink-0 text-red-300"
              />

              <div className="min-w-0 flex-1">
                <h2 className="font-medium text-white">
                  Unable to load teams
                </h2>
                <p className="mt-1 text-sm text-zinc-400">
                  {teamError}
                </p>

                <button
                  type="button"
                  onClick={handleTeamRefresh}
                  className="mt-3 text-sm font-medium text-violet-300 hover:text-violet-200"
                >
                  Try again
                </button>
              </div>
            </div>
          </div>
        )}

        {!isLoadingTeams &&
          !teamError &&
          teams.length === 0 && (
            <div className="rounded-xl border border-dashed border-white/10 bg-[#101012] px-5 py-14 text-center">
              <Users
                size={25}
                className="mx-auto text-zinc-600"
              />
              <h2 className="mt-4 font-medium text-white">
                No accessible teams
              </h2>
              <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-zinc-500">
                Activity becomes available when you have access to a team.
              </p>
            </div>
          )}

        {/* Activity timeline */}
        {!isLoadingTeams && !teamError && selectedTeamId && (
          <section className="overflow-hidden rounded-xl border border-white/[0.08] bg-[#101012]">
            <div className="flex flex-col gap-3 border-b border-white/[0.07] px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="font-semibold text-white">
                  Team timeline
                </h2>
                <p className="mt-1 text-xs text-zinc-500">
                  Most recent activity appears first.
                </p>
              </div>

              <div className="inline-flex items-center gap-2 text-xs text-zinc-500">
                <Clock3 size={14} />
                {PAGE_SIZE} events per page
              </div>
            </div>

            {activityError && (
              <div className="border-b border-red-500/15 bg-red-500/[0.04] px-5 py-4">
                <div className="flex items-start gap-3">
                  <AlertCircle
                    size={17}
                    className="mt-0.5 shrink-0 text-red-300"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-red-200">
                      Could not load activity
                    </p>
                    <p className="mt-1 break-words text-sm text-zinc-400">
                      {activityError}
                    </p>
                    <button
                      type="button"
                      onClick={handleRefresh}
                      className="mt-2 text-sm text-violet-300 hover:text-violet-200"
                    >
                      Retry request
                    </button>
                  </div>
                </div>
              </div>
            )}

            {memberError && !activityError && (
              <div className="border-b border-amber-500/15 bg-amber-500/[0.035] px-5 py-3 text-xs text-amber-200/80">
                Member names could not be resolved. Activity remains available.
              </div>
            )}

            {isLoadingActivity && (
              <div className="flex items-center justify-center gap-3 px-5 py-16 text-sm text-zinc-400">
                <Loader2 size={18} className="animate-spin" />
                Loading activity...
              </div>
            )}

            {!isLoadingActivity &&
              !activityError &&
              filteredActivities.length === 0 && (
                <div className="px-5 py-16 text-center">
                  <div className="mx-auto flex size-12 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.025]">
                    {searchTerm ? (
                      <Search size={21} className="text-zinc-500" />
                    ) : (
                      <ActivityIcon
                        size={21}
                        className="text-zinc-500"
                      />
                    )}
                  </div>

                  <h3 className="mt-4 font-medium text-white">
                    {searchTerm
                      ? "No matching activity"
                      : "No activity to show"}
                  </h3>

                  <p className="mx-auto mt-1 max-w-sm text-sm leading-6 text-zinc-500">
                    {searchTerm
                      ? "Try a different search term or clear your search."
                      : "There are no events matching this filter yet."}
                  </p>

                  {searchTerm && (
                    <button
                      type="button"
                      onClick={() => setSearchTerm("")}
                      className="mt-3 text-sm font-medium text-violet-300 hover:text-violet-200"
                    >
                      Clear search
                    </button>
                  )}
                </div>
              )}

            {!isLoadingActivity &&
              !activityError &&
              filteredActivities.length > 0 && (
                <div className="divide-y divide-white/[0.055]">
                  {filteredActivities.map((activity, index) => {
                    const meta = getActionMeta(activity.action);
                    const Icon = meta.icon;
                    const actor = getActorLabel(
                      activity.actor_id,
                      memberMap,
                    );
                    const details = formatDetailEntries(
                      activity.details,
                    );

                    const key =
                      activity.id ??
                      `${activity.action}-${activity.created_at}-${index}`;

                    return (
                      <article
                        key={key}
                        className="flex gap-3 px-4 py-5 transition hover:bg-white/[0.015] sm:gap-4 sm:px-5"
                      >
                        <div
                          className={`flex size-10 shrink-0 items-center justify-center rounded-xl border ${meta.tone}`}
                        >
                          <Icon size={18} />
                        </div>

                        <div className="min-w-0 flex-1">
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <h3 className="text-sm font-medium text-zinc-100">
                                  {meta.label}
                                </h3>

                                <span
                                  className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-medium ${meta.tone}`}
                                >
                                  {humanize(activity.action)}
                                </span>
                              </div>

                              <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-sm text-zinc-400">
                                <UserRound
                                  size={13}
                                  className="shrink-0 text-zinc-500"
                                />
                                <span className="font-medium text-zinc-300">
                                  {actor}
                                </span>
                                <span className="text-zinc-600">
                                  performed this action
                                </span>
                              </p>
                            </div>

                            <time
                              dateTime={activity.created_at}
                              className="shrink-0 text-xs text-zinc-500"
                            >
                              {formatDate(activity.created_at)}
                            </time>
                          </div>

                          {details.length > 0 && (
                            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                              {details.map(([label, value]) => (
                                <div
                                  key={label}
                                  className="min-w-0 rounded-lg border border-white/[0.055] bg-white/[0.018] px-3 py-2"
                                >
                                  <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-600">
                                    {label}
                                  </p>
                                  <p className="mt-1 break-words text-sm text-zinc-300">
                                    {value}
                                  </p>
                                </div>
                              ))}
                            </div>
                          )}

                          {activity.work_item_id && (
                            <div className="mt-3">
                              <Link
                                href="/work-items"
                                className="inline-flex items-center gap-1.5 text-xs font-medium text-violet-300 transition hover:text-violet-200"
                              >
                                View work items
                                <ArrowUpRight size={13} />
                              </Link>
                            </div>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}

            {/* Pagination */}
            {!isLoadingActivity &&
              !activityError &&
              total > 0 && (
                <footer className="flex flex-col gap-3 border-t border-white/[0.07] px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
                  <p className="text-xs text-zinc-500">
                    Showing{" "}
                    <span className="font-medium text-zinc-300">
                      {page * PAGE_SIZE + 1}
                    </span>
                    {"–"}
                    <span className="font-medium text-zinc-300">
                      {Math.min((page + 1) * PAGE_SIZE, total)}
                    </span>
                    {" of "}
                    <span className="font-medium text-zinc-300">
                      {total}
                    </span>
                    {" events"}
                  </p>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handlePreviousPage}
                      disabled={page === 0 || isLoadingActivity}
                      className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-white/10 px-3 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      <ChevronLeft size={14} />
                      Previous
                    </button>

                    <span className="px-2 text-xs tabular-nums text-zinc-500">
                      Page {page + 1} of {totalPages}
                    </span>

                    <button
                      type="button"
                      onClick={handleNextPage}
                      disabled={
                        page + 1 >= totalPages || isLoadingActivity
                      }
                      className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-white/10 px-3 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      Next
                      <ChevronRight size={14} />
                    </button>
                  </div>
                </footer>
              )}
          </section>
        )}

        <p className="px-1 text-xs leading-5 text-zinc-600">
          Activity visibility is controlled by the backend. This page only
          displays events the current account is authorized to view.
          {isLoadingMembers ? " Resolving team member names..." : ""}
        </p>
      </div>
    </main>
  );
}