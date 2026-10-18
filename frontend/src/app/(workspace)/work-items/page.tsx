"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ClipboardList,
  Clock3,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  UserRound,
  X,
} from "lucide-react";

import { api, ApiError, type ServiceResponse } from "@/lib/api-client";
import { useAuth } from "@/providers/auth-provider";

const PAGE_SIZE = 10;

const STATUSES = [
  "open",
  "in_progress",
  "pending_approval",
  "resolved",
  "cancelled",
] as const;

const PRIORITIES = ["low", "medium", "high", "critical"] as const;

const WORK_TYPES = [
  "investigation",
  "action",
  "incident",
  "approval",
] as const;

type WorkStatus = (typeof STATUSES)[number];
type WorkPriority = (typeof PRIORITIES)[number];
type WorkType = (typeof WORK_TYPES)[number];
type QueueMode = "mine" | "team";

interface WorkItem {
  id: string;
  title: string;
  description: string;
  type: WorkType;
  status: WorkStatus;
  priority: WorkPriority;
  team_id: string;
  created_by: string;
  assignee_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

interface Team {
  id: string;
  name: string;
  description?: string | null;
  role?: string;
  membership_role?: string;
}

interface TeamMember {
  user_id: string;
  full_name: string;
  email: string;
  account_status?: string;
}

interface PageData<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

interface CreateWorkItemResponse {
  work_item: WorkItem;
}

interface Filters {
  status: string;
  priority: string;
  type: string;
  unassignedOnly: boolean;
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
  }).format(date);
}

function relativeDate(value?: string | null): string {
  if (!value) return "Date unavailable";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "Date unavailable";

  const minutes = Math.floor((Date.now() - date.getTime()) / 60000);

  if (minutes < 1 && minutes >= 0) return "Just now";
  if (minutes < 60 && minutes >= 0) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);

  if (hours < 24 && hours >= 0) return `${hours}h ago`;

  return formatDate(value);
}

function statusClasses(status: string): string {
  switch (status) {
    case "open":
      return "border-slate-400/20 bg-slate-400/[0.07] text-slate-300";
    case "in_progress":
      return "border-blue-400/20 bg-blue-400/[0.07] text-blue-300";
    case "pending_approval":
      return "border-amber-400/20 bg-amber-400/[0.07] text-amber-300";
    case "resolved":
      return "border-emerald-400/20 bg-emerald-400/[0.07] text-emerald-300";
    case "cancelled":
      return "border-red-400/20 bg-red-400/[0.07] text-red-300";
    default:
      return "border-white/[0.08] bg-white/[0.035] text-zinc-400";
  }
}

function priorityClasses(priority: string): string {
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

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return "The API could not be reached. Check that the backend is running.";
    }

    if (error.status === 401) {
      return "Your session could not be verified. Please sign in again.";
    }

    if (error.status === 403) {
      return "You do not have permission to perform this operation.";
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

function SelectField({
  value,
  onChange,
  options,
  placeholder,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  options: readonly string[];
  placeholder: string;
  disabled?: boolean;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="h-10 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#111114] pl-3 pr-9 text-xs text-zinc-300 outline-none transition hover:border-white/[0.14] focus:border-indigo-400/50 disabled:opacity-50"
      >
        <option value="">{placeholder}</option>

        {options.map((option) => (
          <option key={option} value={option}>
            {label(option)}
          </option>
        ))}
      </select>

      <ChevronDown
        size={14}
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
      />
    </div>
  );
}

export default function WorkItemsPage() {
  const { user } = useAuth();

  const [items, setItems] = useState<WorkItem[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [memberNames, setMemberNames] = useState<Record<string, string>>({});

  const [queue, setQueue] = useState<QueueMode>("mine");
  const [selectedTeamId, setSelectedTeamId] = useState("");

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const [filters, setFilters] = useState<Filters>({
    status: "",
    priority: "",
    type: "",
    unassignedOnly: false,
  });

  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);

  const [isLoading, setIsLoading] = useState(true);
  const [teamsLoading, setTeamsLoading] = useState(true);
  const [teamsError, setTeamsError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [newTeamId, setNewTeamId] = useState("");
  const [newType, setNewType] = useState<WorkType>("investigation");
  const [newPriority, setNewPriority] =
    useState<WorkPriority>("medium");
  const [createError, setCreateError] = useState("");

  const [filtersOpen, setFiltersOpen] = useState(false);

  const requestSequence = useRef(0);
  const memberSequence = useRef(0);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const visibleMemberNames =
    queue === "mine" && user?.id && user.full_name
      ? { ...memberNames, [user.id]: user.full_name }
      : memberNames;

  const loadTeams = useCallback(async () => {
    try {
      const response = await api.get<PageData<Team>>("users/me/teams", {
        query: { limit: 100, offset: 0 },
      });

      const data = response.outputs.data;

      if (!data) {
        throw new Error("The teams response did not contain data.");
      }

      setTeams(data.items);
      setTeamsError("");

      setSelectedTeamId((current) =>
        current && data.items.some((team) => team.id === current)
          ? current
          : data.items[0]?.id ?? "",
      );

      setNewTeamId((current) =>
        current && data.items.some((team) => team.id === current)
          ? current
          : data.items[0]?.id ?? "",
      );
    } catch (error) {
      setTeamsError(getErrorMessage(error));
    } finally {
      setTeamsLoading(false);
    }
  }, []);

  const loadItems = useCallback(async () => {
    const sequence = ++requestSequence.current;

    if (queue === "team" && !selectedTeamId) {
      await Promise.resolve();

      if (sequence === requestSequence.current) {
        setItems([]);
        setTotal(0);
        setIsLoading(false);
      }

      return;
    }

    const query = {
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
      status: filters.status || undefined,
      priority: filters.priority || undefined,
      type: filters.type || undefined,
      search: search.trim() || undefined,
      ...(queue === "team" && filters.unassignedOnly
        ? { unassigned_only: true }
        : {}),
    };

    try {
      const endpoint =
        queue === "mine"
          ? "work-items/mine"
          : `teams/${encodeURIComponent(selectedTeamId)}/work-items`;

      const response = await api.get<PageData<WorkItem>>(endpoint, {
        query,
      });

      if (sequence !== requestSequence.current) return;

      const data = response.outputs.data;

      if (!data) {
        throw new Error("The work-items response did not contain data.");
      }

      setItems(data.items);
      setTotal(data.total);
      setLoadError("");
    } catch (error) {
      if (sequence !== requestSequence.current) return;

      setItems([]);
      setTotal(0);
      setLoadError(getErrorMessage(error));
    } finally {
      if (sequence === requestSequence.current) {
        setIsLoading(false);
      }
    }
  }, [
    queue,
    selectedTeamId,
    page,
    filters.status,
    filters.priority,
    filters.type,
    filters.unassignedOnly,
    search,
  ]);

  useEffect(() => {
    void loadTeams();
  }, [loadTeams]);

  useEffect(() => {
    void loadItems();

    return () => {
      requestSequence.current += 1;
    };
  }, [loadItems]);

  useEffect(() => {
    const sequence = ++memberSequence.current;

    if (queue !== "team" || !selectedTeamId) {
      setMemberNames({});
      return;
    }

    let cancelled = false;

    async function loadTeamMembers() {
      const result = await loadSafely(
        api.get<PageData<TeamMember>>(
          `teams/${encodeURIComponent(selectedTeamId)}/members`,
          { query: { limit: 100, offset: 0 } },
        ),
      );

      if (cancelled || sequence !== memberSequence.current) return;

      const names: Record<string, string> = {};

      for (const member of result.data?.items ?? []) {
        if (
          member.user_id &&
          member.full_name &&
          (member.account_status === undefined ||
            member.account_status === "active")
        ) {
          names[member.user_id] = member.full_name;
        }
      }

      setMemberNames(names);
    }

    void loadTeamMembers();

    return () => {
      cancelled = true;
    };
  }, [queue, selectedTeamId]);

  function selectQueue(nextQueue: QueueMode) {
    setIsLoading(true);
    setLoadError("");
    setNotice("");
    setQueue(nextQueue);
    setPage(0);
  }

  function changeFilter<K extends keyof Filters>(
    key: K,
    value: Filters[K],
  ) {
    setIsLoading(true);
    setLoadError("");
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(0);
    setNotice("");
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setIsLoading(true);
    setLoadError("");
    setSearch(searchInput.trim());
    setPage(0);
  }

  function resetFilters() {
    setIsLoading(true);
    setLoadError("");

    setFilters({
      status: "",
      priority: "",
      type: "",
      unassignedOnly: false,
    });

    setSearchInput("");
    setSearch("");
    setPage(0);
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (creating) return;

    setCreateError("");

    if (!newTeamId) {
      setCreateError("Select a team before creating the work item.");
      return;
    }

    if (!title.trim() || title.trim().length > 200) {
      setCreateError("Title must contain between 1 and 200 characters.");
      return;
    }

    if (!description.trim()) {
      setCreateError("Description cannot be empty.");
      return;
    }

    setCreating(true);

    try {
      const response = await api.post<CreateWorkItemResponse>(
        "work-items",
        {
          title: title.trim(),
          description: description.trim(),
          type: newType,
          team_id: newTeamId,
          priority: newPriority,
          assignee_id: null,
        },
      );

      const created = response.outputs.data?.work_item;

      if (!created) {
        throw new Error("The API did not return the created work item.");
      }

      setTitle("");
      setDescription("");
      setNewType("investigation");
      setNewPriority("medium");
      setCreateOpen(false);
      setNotice(`Created "${created.title}" successfully.`);

      setIsLoading(true);
      setLoadError("");
      setQueue("team");
      setSelectedTeamId(created.team_id);
      setPage(0);
      setSearch("");
      setSearchInput("");

      setFilters({
        status: "",
        priority: "",
        type: "",
        unassignedOnly: false,
      });
    } catch (error) {
      setCreateError(getErrorMessage(error));
    } finally {
      setCreating(false);
    }
  }

  function refreshItems() {
    setIsLoading(true);
    setLoadError("");
    void loadItems();
  }

  const firstItem = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const lastItem = Math.min((page + 1) * PAGE_SIZE, total);

  return (
    <div className="mx-auto max-w-[1600px] space-y-6">
      <section className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 flex items-center gap-2 text-xs text-zinc-500">
            <span>Workspace</span>
            <span className="text-zinc-700">/</span>
            <span className="text-zinc-300">Work items</span>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Work items
          </h1>

          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
            Find, prioritize, and manage the operational work that needs
            attention.
          </p>
        </div>

        <button
          type="button"
          onClick={() => {
            setCreateError("");
            setCreateOpen(true);
          }}
          disabled={teamsLoading || teams.length === 0}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-semibold text-zinc-950 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus size={15} />
          Create work item
        </button>
      </section>

      {notice && (
        <div
          role="status"
          className="flex items-center gap-3 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.05] px-4 py-3 text-sm text-emerald-200"
        >
          <CheckCircle2 size={17} />
          <span className="flex-1">{notice}</span>

          <button
            type="button"
            onClick={() => setNotice("")}
            aria-label="Dismiss message"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {teamsError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-xl border border-amber-400/20 bg-amber-400/[0.04] px-4 py-3"
        >
          <AlertCircle size={17} className="mt-0.5 shrink-0 text-amber-300" />

          <div className="flex-1">
            <p className="text-sm text-zinc-200">
              Could not load your team memberships.
            </p>
            <p className="mt-1 text-xs text-zinc-500">{teamsError}</p>
          </div>

          <button
            type="button"
            onClick={() => {
              setTeamsLoading(true);
              setTeamsError("");
              void loadTeams();
            }}
            className="text-xs text-zinc-300 underline underline-offset-4"
          >
            Retry
          </button>
        </div>
      )}

      <section className="flex flex-col justify-between gap-4 border-b border-white/[0.07] pb-4 md:flex-row md:items-center">
        <div className="inline-flex w-fit rounded-lg border border-white/[0.08] bg-white/[0.02] p-1">
          <button
            type="button"
            onClick={() => selectQueue("mine")}
            className={[
              "rounded-md px-4 py-2 text-xs font-medium transition",
              queue === "mine"
                ? "bg-white/[0.09] text-white"
                : "text-zinc-500 hover:text-zinc-200",
            ].join(" ")}
          >
            My work
          </button>

          <button
            type="button"
            onClick={() => selectQueue("team")}
            className={[
              "rounded-md px-4 py-2 text-xs font-medium transition",
              queue === "team"
                ? "bg-white/[0.09] text-white"
                : "text-zinc-500 hover:text-zinc-200",
            ].join(" ")}
          >
            Team queue
          </button>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {queue === "team" && (
            <div className="relative min-w-0 sm:min-w-[210px]">
              <select
                aria-label="Choose team"
                value={selectedTeamId}
                disabled={teamsLoading || teams.length === 0}
                onChange={(event) => {
                  setIsLoading(true);
                  setLoadError("");
                  setSelectedTeamId(event.target.value);
                  setPage(0);
                }}
                className="h-10 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#111114] pl-3 pr-9 text-xs text-zinc-300 outline-none focus:border-indigo-400/50 disabled:opacity-50"
              >
                <option value="">
                  {teamsLoading ? "Loading teams..." : "Select team"}
                </option>

                {teams.map((team) => (
                  <option key={team.id} value={team.id}>
                    {team.name}
                  </option>
                ))}
              </select>

              <ChevronDown
                size={14}
                className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
              />
            </div>
          )}

          <button
            type="button"
            onClick={refreshItems}
            disabled={isLoading}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs text-zinc-400 transition hover:bg-white/[0.04] hover:text-white disabled:opacity-50"
          >
            <RefreshCw
              size={13}
              className={isLoading ? "animate-spin" : ""}
            />
            Refresh
          </button>
        </div>
      </section>

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
              placeholder="Search titles and descriptions..."
              aria-label="Search work items"
              className="h-11 w-full rounded-lg border border-white/[0.08] bg-white/[0.02] pl-10 pr-4 text-sm text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-indigo-400/50"
            />
          </div>

          <button
            type="submit"
            className="h-11 rounded-lg border border-white/[0.08] bg-white/[0.04] px-5 text-xs font-medium text-zinc-200 hover:bg-white/[0.08]"
          >
            Search
          </button>

          <button
            type="button"
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
            className={[
              "inline-flex h-11 items-center justify-center gap-2 rounded-lg border px-4 text-xs transition",
              filtersOpen
                ? "border-indigo-400/30 bg-indigo-400/[0.07] text-indigo-200"
                : "border-white/[0.08] text-zinc-400 hover:bg-white/[0.04]",
            ].join(" ")}
          >
            <SlidersHorizontal size={14} />
            Filters
            <ChevronDown
              size={13}
              className={filtersOpen ? "rotate-180 transition" : "transition"}
            />
          </button>
        </form>

        {filtersOpen && (
          <div className="grid grid-cols-1 gap-3 rounded-xl border border-white/[0.07] bg-white/[0.015] p-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="space-y-2">
              <label className="text-[11px] font-medium text-zinc-500">
                Status
              </label>
              <SelectField
                value={filters.status}
                onChange={(value) => changeFilter("status", value)}
                options={STATUSES}
                placeholder="All statuses"
              />
            </div>

            <div className="space-y-2">
              <label className="text-[11px] font-medium text-zinc-500">
                Priority
              </label>
              <SelectField
                value={filters.priority}
                onChange={(value) => changeFilter("priority", value)}
                options={PRIORITIES}
                placeholder="All priorities"
              />
            </div>

            <div className="space-y-2">
              <label className="text-[11px] font-medium text-zinc-500">
                Type
              </label>
              <SelectField
                value={filters.type}
                onChange={(value) => changeFilter("type", value)}
                options={WORK_TYPES}
                placeholder="All types"
              />
            </div>

            <div className="flex items-end">
              <button
                type="button"
                onClick={resetFilters}
                className="h-10 text-xs text-zinc-400 underline decoration-white/15 underline-offset-4 hover:text-white"
              >
                Clear all filters
              </button>
            </div>

            {queue === "team" && (
              <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-300 sm:col-span-2 xl:col-span-4">
                <input
                  type="checkbox"
                  checked={filters.unassignedOnly}
                  onChange={(event) =>
                    changeFilter("unassignedOnly", event.target.checked)
                  }
                  className="h-4 w-4 accent-indigo-400"
                />
                Show only unassigned work
              </label>
            )}
          </div>
        )}
      </section>

      <section className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-zinc-100">
            {queue === "mine" ? "Assigned to me" : "Team work queue"}
          </h2>
          <p className="mt-1 text-xs text-zinc-500">
            {isLoading
              ? "Loading work items..."
              : `${total} matching item${total === 1 ? "" : "s"}`}
          </p>
        </div>
      </section>

      <section className="overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.015]">
        <div className="hidden grid-cols-[minmax(0,1.8fr)_130px_110px_150px_100px] gap-4 border-b border-white/[0.07] bg-white/[0.015] px-5 py-3 lg:grid">
          {["Work item", "Status", "Priority", "Assignee", "Updated"].map(
            (heading) => (
              <span
                key={heading}
                className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600"
              >
                {heading}
              </span>
            ),
          )}
        </div>

        {isLoading ? (
          <div className="space-y-3 p-5" aria-label="Loading work items">
            {[1, 2, 3, 4, 5].map((row) => (
              <div
                key={row}
                className="h-[76px] animate-pulse rounded-lg bg-white/[0.035]"
              />
            ))}
          </div>
        ) : loadError ? (
          <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
            <AlertCircle size={24} className="text-red-300" />
            <p className="mt-4 text-sm font-medium text-zinc-200">
              Could not load work items
            </p>
            <p className="mt-2 max-w-md text-xs leading-5 text-zinc-500">
              {loadError}
            </p>
            <button
              type="button"
              onClick={refreshItems}
              className="mt-5 rounded-lg border border-white/10 px-4 py-2 text-xs text-zinc-200 hover:bg-white/[0.04]"
            >
              Try again
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="flex min-h-72 flex-col items-center justify-center px-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-white/[0.07] bg-white/[0.025]">
              <ClipboardList size={22} className="text-zinc-500" />
            </div>

            <h3 className="mt-4 text-sm font-medium text-zinc-200">
              No work items found
            </h3>

            <p className="mt-2 max-w-sm text-xs leading-5 text-zinc-500">
              {search || filters.status || filters.priority || filters.type
                ? "Try changing your search or clearing the filters."
                : queue === "mine"
                  ? "Nothing is assigned to you yet. Check the team queue or create a work item."
                  : "This team has no work items matching the selected filters."}
            </p>

            <button
              type="button"
              onClick={() => {
                setCreateError("");
                setCreateOpen(true);
              }}
              disabled={teams.length === 0}
              className="mt-5 inline-flex items-center gap-2 rounded-lg bg-zinc-100 px-4 py-2 text-xs font-semibold text-zinc-950 hover:bg-white disabled:opacity-50"
            >
              <Plus size={14} />
              Create work item
            </button>
          </div>
        ) : (
          <div className="divide-y divide-white/[0.055]">
            {items.map((item) => {
              const teamName =
                teams.find((team) => team.id === item.team_id)?.name ??
                (queue === "team" ? "Selected team" : "Team");

              const assigneeName = item.assignee_id
                ? visibleMemberNames[item.assignee_id] ??
                  (item.assignee_id === user?.id
                    ? user.full_name
                    : "Team member")
                : "Unassigned";

              return (
                <div
                  key={item.id}
                  className="grid grid-cols-1 gap-3 px-4 py-4 transition hover:bg-white/[0.02] sm:px-5 lg:grid-cols-[minmax(0,1.8fr)_130px_110px_150px_100px] lg:items-center lg:gap-4"
                >
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/[0.07] bg-white/[0.025]">
                      <ClipboardList size={16} className="text-zinc-400" />
                    </div>

                    <div className="min-w-0 flex-1">
                      <Link
                        href={`/work-items/${encodeURIComponent(item.id)}`}
                        className="line-clamp-2 text-sm font-medium text-zinc-200 transition hover:text-white"
                      >
                        {item.title}
                      </Link>

                      <p className="mt-1 line-clamp-1 text-xs text-zinc-500">
                        {item.description}
                      </p>

                      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-zinc-600">
                        <span>{label(item.type)}</span>
                        <span>·</span>
                        <span>{teamName}</span>
                      </div>
                    </div>
                  </div>

                  <div>
                    <span
                      className={`inline-flex rounded-md border px-2 py-1 text-[10px] font-medium ${statusClasses(item.status)}`}
                    >
                      {label(item.status)}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 lg:block">
                    <span className="text-[10px] text-zinc-600 lg:hidden">
                      Priority
                    </span>
                    <span
                      className={`inline-flex items-center gap-1.5 text-xs ${priorityClasses(item.priority)}`}
                    >
                      {label(item.priority)}
                    </span>
                  </div>

                  <div className="flex min-w-0 items-center gap-2 text-xs text-zinc-400">
                    <UserRound
                      size={14}
                      className="shrink-0 text-zinc-600"
                    />
                    <span className="truncate">{assigneeName}</span>
                  </div>

                  <div className="flex items-center justify-between gap-3 text-[11px] text-zinc-500 lg:justify-end">
                    <span className="inline-flex items-center gap-1.5 lg:hidden">
                      <Clock3 size={12} />
                      Updated
                    </span>
                    <span title={item.updated_at}>
                      {relativeDate(item.updated_at)}
                    </span>
                    <Link
                      href={`/work-items/${encodeURIComponent(item.id)}`}
                      aria-label={`Open ${item.title}`}
                      className="text-zinc-600 hover:text-white"
                    >
                      <ArrowRight size={15} />
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {!isLoading && !loadError && total > 0 && (
          <div className="flex flex-col gap-3 border-t border-white/[0.07] px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
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
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs text-zinc-300 hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-35"
              >
                <ArrowLeft size={13} />
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
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs text-zinc-300 hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-35"
              >
                Next
                <ArrowRight size={13} />
              </button>
            </div>
          </div>
        )}
      </section>

      {createOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-5"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !creating) {
              setCreateOpen(false);
            }
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-work-item-title"
            className="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-t-2xl border border-white/[0.09] bg-[#111114] p-5 shadow-2xl shadow-black/40 sm:rounded-2xl sm:p-7"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.17em] text-zinc-500">
                  Work management
                </p>
                <h2
                  id="create-work-item-title"
                  className="mt-2 text-xl font-semibold text-zinc-100"
                >
                  Create work item
                </h2>
                <p className="mt-2 text-xs leading-5 text-zinc-500">
                  Describe the work, choose its team and priority, and create
                  a record that can be tracked through its workflow.
                </p>
              </div>

              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                disabled={creating}
                aria-label="Close dialog"
                className="rounded-lg p-2 text-zinc-500 hover:bg-white/[0.05] hover:text-white disabled:opacity-50"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreate} className="mt-6 space-y-5">
              <div className="space-y-2">
                <label
                  htmlFor="work-title"
                  className="block text-xs font-medium text-zinc-300"
                >
                  Title <span className="text-red-300">*</span>
                </label>
                <input
                  id="work-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  required
                  maxLength={200}
                  placeholder="e.g. Investigate delayed payment processing"
                  disabled={creating}
                  className="h-11 w-full rounded-lg border border-white/[0.08] bg-white/[0.025] px-3.5 text-sm outline-none placeholder:text-zinc-600 focus:border-indigo-400/50 disabled:opacity-50"
                />
                <p className="text-right text-[10px] text-zinc-600">
                  {title.length}/200
                </p>
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="work-description"
                  className="block text-xs font-medium text-zinc-300"
                >
                  Description <span className="text-red-300">*</span>
                </label>
                <textarea
                  id="work-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  required
                  rows={4}
                  placeholder="Explain what happened, why it matters, and what needs investigation or action."
                  disabled={creating}
                  className="w-full resize-y rounded-lg border border-white/[0.08] bg-white/[0.025] px-3.5 py-3 text-sm leading-6 outline-none placeholder:text-zinc-600 focus:border-indigo-400/50 disabled:opacity-50"
                />
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <label
                    htmlFor="work-team"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Team <span className="text-red-300">*</span>
                  </label>
                  <div className="relative">
                    <select
                      id="work-team"
                      value={newTeamId}
                      onChange={(event) => setNewTeamId(event.target.value)}
                      required
                      disabled={
                        creating || teamsLoading || teams.length === 0
                      }
                      className="h-11 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#17171b] px-3.5 pr-9 text-sm outline-none focus:border-indigo-400/50 disabled:opacity-50"
                    >
                      <option value="">Select a team</option>
                      {teams.map((team) => (
                        <option key={team.id} value={team.id}>
                          {team.name}
                        </option>
                      ))}
                    </select>
                    <ChevronDown
                      size={14}
                      className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <label
                    htmlFor="work-type"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Type
                  </label>
                  <div className="relative">
                    <select
                      id="work-type"
                      value={newType}
                      onChange={(event) =>
                        setNewType(event.target.value as WorkType)
                      }
                      disabled={creating}
                      className="h-11 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#17171b] px-3.5 pr-9 text-sm outline-none focus:border-indigo-400/50 disabled:opacity-50"
                    >
                      {WORK_TYPES.map((option) => (
                        <option key={option} value={option}>
                          {label(option)}
                        </option>
                      ))}
                    </select>
                    <ChevronDown
                      size={14}
                      className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
                    />
                  </div>
                </div>

                <div className="space-y-2 sm:col-span-2">
                  <label
                    htmlFor="work-priority"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Priority
                  </label>
                  <div className="relative">
                    <select
                      id="work-priority"
                      value={newPriority}
                      onChange={(event) =>
                        setNewPriority(event.target.value as WorkPriority)
                      }
                      disabled={creating}
                      className="h-11 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#17171b] px-3.5 pr-9 text-sm outline-none focus:border-indigo-400/50 disabled:opacity-50"
                    >
                      {PRIORITIES.map((option) => (
                        <option key={option} value={option}>
                          {label(option)}
                        </option>
                      ))}
                    </select>
                    <ChevronDown
                      size={14}
                      className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
                    />
                  </div>
                </div>
              </div>

              {!teamsLoading && teams.length === 0 && (
                <p className="rounded-lg border border-amber-400/20 bg-amber-400/[0.04] p-3 text-xs leading-5 text-amber-200">
                  You need an accessible team membership before creating work.
                </p>
              )}

              {createError && (
                <p
                  role="alert"
                  className="rounded-lg border border-red-400/20 bg-red-400/[0.05] p-3 text-xs leading-5 text-red-300"
                >
                  {createError}
                </p>
              )}

              <div className="flex flex-col-reverse gap-2 border-t border-white/[0.07] pt-4 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  onClick={() => setCreateOpen(false)}
                  disabled={creating}
                  className="h-10 rounded-lg border border-white/[0.08] px-4 text-xs font-medium text-zinc-300 hover:bg-white/[0.04] disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={
                    creating ||
                    teamsLoading ||
                    teams.length === 0 ||
                    !newTeamId ||
                    !title.trim() ||
                    !description.trim()
                  }
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-semibold text-zinc-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {creating ? (
                    <>
                      <RefreshCw size={13} className="animate-spin" />
                      Creating...
                    </>
                  ) : (
                    <>
                      <Plus size={14} />
                      Create work item
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