"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Users,
  UserPlus,
  X,
} from "lucide-react";

import { api, ApiError } from "@/lib/api-client";

const PAGE_SIZE = 10;

type TeamRole = "lead" | "member" | "approver";

interface Team {
  id: string;
  name: string;
  description?: string | null;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
  membership_role?: TeamRole;
  membership_joined_at?: string;
}

interface TeamEnvelope {
  team: Team;
}

interface TeamMember {
  membership_id: string;
  team_id: string;
  user_id: string;
  role: TeamRole;
  joined_at?: string;
  full_name: string;
  email: string;
  account_status: string;
}

interface Account {
  id: string;
  full_name: string;
  email: string;
  account_status: string;
}

interface PageData<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

type ModalName = "create-team" | "edit-team" | "add-member" | null;

function label(value?: string | null): string {
  if (!value) return "Unknown";

  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
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

    if (error.status === 404) {
      return "The requested record was not found or is no longer available.";
    }

    if (error.status === 409) {
      return (
        error.message ||
        "This operation conflicts with the current team state."
      );
    }

    return error.message;
  }

  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}

function roleClasses(role: string): string {
  switch (role) {
    case "lead":
      return "border-indigo-400/20 bg-indigo-400/[0.07] text-indigo-200";
    case "approver":
      return "border-amber-400/20 bg-amber-400/[0.07] text-amber-200";
    default:
      return "border-white/[0.08] bg-white/[0.03] text-zinc-400";
  }
}

function Initials({ name }: { name: string }) {
  const initials =
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0] ?? "")
      .join("")
      .toUpperCase() || "U";

  return (
    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-indigo-400/10 bg-indigo-400/[0.07] text-xs font-semibold text-indigo-200">
      {initials}
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] font-medium ${roleClasses(role)}`}
    >
      {role === "lead" && <ShieldCheck size={11} />}
      {label(role)}
    </span>
  );
}

function SectionHeading({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>

      {description && (
        <p className="mt-1 text-xs leading-5 text-zinc-500">
          {description}
        </p>
      )}
    </div>
  );
}

export default function TeamsPage() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState("");

  const [members, setMembers] = useState<TeamMember[]>([]);
  const [memberTotal, setMemberTotal] = useState(0);

  const [teamSearchInput, setTeamSearchInput] = useState("");
  const [teamSearch, setTeamSearch] = useState("");

  const [memberSearchInput, setMemberSearchInput] = useState("");
  const [memberSearch, setMemberSearch] = useState("");

  const [isLoading, setIsLoading] = useState(true);
  const [membersLoading, setMembersLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [savingMemberId, setSavingMemberId] = useState<string | null>(
    null,
  );

  const [pageError, setPageError] = useState("");
  const [memberError, setMemberError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");

  const [modal, setModal] = useState<ModalName>(null);

  const [draftName, setDraftName] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [modalError, setModalError] = useState("");

  const [directoryQuery, setDirectoryQuery] = useState("");
  const [directoryAccounts, setDirectoryAccounts] = useState<Account[]>(
    [],
  );
  const [directoryError, setDirectoryError] = useState("");
  const [directoryLoading, setDirectoryLoading] = useState(false);

  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [newMemberRole, setNewMemberRole] = useState<TeamRole>("member");
  const [draftRoles, setDraftRoles] = useState<Record<string, TeamRole>>(
    {},
  );

  const teamRequestVersion = useRef(0);
  const memberRequestVersion = useRef(0);
  const directoryRequestVersion = useRef(0);

  const selectedTeam = useMemo(
    () => teams.find((team) => team.id === selectedTeamId) ?? null,
    [teams, selectedTeamId],
  );

  const visibleTeams = useMemo(() => {
    const query = teamSearch.trim().toLowerCase();

    if (!query) return teams;

    return teams.filter(
      (team) =>
        team.name.toLowerCase().includes(query) ||
        (team.description ?? "").toLowerCase().includes(query),
    );
  }, [teams, teamSearch]);

  const visibleMembers = useMemo(() => {
    const query = memberSearch.trim().toLowerCase();

    if (!query) return members;

    return members.filter(
      (member) =>
        member.full_name.toLowerCase().includes(query) ||
        member.email.toLowerCase().includes(query) ||
        member.role.toLowerCase().includes(query),
    );
  }, [members, memberSearch]);

  const loadTeams = useCallback(async (preferredTeamId?: string) => {
    const version = ++teamRequestVersion.current;

    try {
      const response = await api.get<PageData<Team>>("users/me/teams", {
        query: {
          limit: 100,
          offset: 0,
          search: teamSearch || undefined,
        },
      });

      if (version !== teamRequestVersion.current) return;

      const data = response.outputs.data;

      if (!data) {
        setTeams([]);
        setSelectedTeamId("");
        setPageError("The teams response did not contain data.");
        return;
      }

      setTeams(data.items);

      setSelectedTeamId((current) => {
        if (
          preferredTeamId &&
          data.items.some((team) => team.id === preferredTeamId)
        ) {
          return preferredTeamId;
        }

        if (current && data.items.some((team) => team.id === current)) {
          return current;
        }

        return data.items[0]?.id ?? "";
      });

      setPageError("");
    } catch (error) {
      if (version !== teamRequestVersion.current) return;

      setPageError(getErrorMessage(error));
    } finally {
      if (version === teamRequestVersion.current) {
        setIsLoading(false);
      }
    }
  }, [teamSearch]);

  const loadMembers = useCallback(async () => {
    const version = ++memberRequestVersion.current;

    if (!selectedTeamId) {
      setMembers([]);
      setMemberTotal(0);
      setDraftRoles({});
      setMembersLoading(false);
      return;
    }

    try {
      const response = await api.get<PageData<TeamMember>>(
        `teams/${encodeURIComponent(selectedTeamId)}/members`,
        {
          query: {
            limit: PAGE_SIZE,
            offset: 0,
            search: memberSearch || undefined,
          },
        },
      );

      if (version !== memberRequestVersion.current) return;

      const data = response.outputs.data;

      if (!data) {
        setMembers([]);
        setMemberTotal(0);
        setDraftRoles({});
        setMemberError("The membership response did not contain data.");
        return;
      }

      setMembers(data.items);
      setMemberTotal(data.total);

      setDraftRoles(
        Object.fromEntries(
          data.items.map((member) => [member.user_id, member.role]),
        ) as Record<string, TeamRole>,
      );

      setMemberError("");
    } catch (error) {
      if (version !== memberRequestVersion.current) return;

      setMembers([]);
      setMemberTotal(0);
      setDraftRoles({});
      setMemberError(getErrorMessage(error));
    } finally {
      if (version === memberRequestVersion.current) {
        setMembersLoading(false);
      }
    }
  }, [selectedTeamId, memberSearch]);

  useEffect(() => {
    void loadTeams();

    return () => {
      teamRequestVersion.current += 1;
    };
  }, [loadTeams]);

  useEffect(() => {
    void loadMembers();

    return () => {
      memberRequestVersion.current += 1;
    };
  }, [loadMembers]);

  async function refreshAll() {
    setIsLoading(true);
    setMembersLoading(true);
    setPageError("");
    setMemberError("");
    setActionError("");
    setNotice("");

    await loadTeams(selectedTeamId || undefined);
  }

  function openCreateTeam() {
    setDraftName("");
    setDraftDescription("");
    setModalError("");
    setModal("create-team");
  }

  function openEditTeam() {
    if (!selectedTeam) return;

    setDraftName(selectedTeam.name);
    setDraftDescription(selectedTeam.description ?? "");
    setModalError("");
    setModal("edit-team");
  }

  function openAddMember() {
    setDirectoryQuery("");
    setDirectoryAccounts([]);
    setDirectoryError("");
    setSelectedAccountId("");
    setNewMemberRole("member");
    setModalError("");
    setModal("add-member");
  }

  async function searchAccounts(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedTeam) {
      setDirectoryError("Select a team before searching for members.");
      return;
    }

    if (!directoryQuery.trim()) {
      setDirectoryError("Enter a name or email address to search.");
      return;
    }

    if (directoryQuery.trim().length < 2) {
      setDirectoryError("Enter at least two characters to search.");
      return;
    }

    const version = ++directoryRequestVersion.current;

    setDirectoryLoading(true);
    setDirectoryError("");
    setDirectoryAccounts([]);
    setSelectedAccountId("");

    try {
      const response = await api.get<PageData<Account>>("accounts", {
        query: {
          limit: 20,
          offset: 0,
          account_status: "active",
          search: directoryQuery.trim(),
          team_id: selectedTeam.id,
        },
      });

      if (version !== directoryRequestVersion.current) return;

      const data = response.outputs.data;

      if (!data) {
        setDirectoryAccounts([]);
        setDirectoryError("The account directory returned no data.");
        return;
      }

      const existingIds = new Set(members.map((member) => member.user_id));

      setDirectoryAccounts(
        data.items.filter((account) => !existingIds.has(account.id)),
      );

      if (data.items.length === 0) {
        setDirectoryError("No active accounts matched that search.");
      } else if (
        data.items.every((account) => existingIds.has(account.id))
      ) {
        setDirectoryError("All matching accounts are already members.");
      }
    } catch (error) {
      if (version !== directoryRequestVersion.current) return;

      setDirectoryAccounts([]);
      setDirectoryError(getErrorMessage(error));
    } finally {
      if (version === directoryRequestVersion.current) {
        setDirectoryLoading(false);
      }
    }
  }

  async function saveTeam(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isSaving) return;

    const name = draftName.trim();
    const description = draftDescription.trim();

    if (!name || name.length > 100) {
      setModalError("Team name must contain between 1 and 100 characters.");
      return;
    }

    setIsSaving(true);
    setModalError("");
    setActionError("");
    setNotice("");

    try {
      if (modal === "create-team") {
        const response = await api.post<TeamEnvelope>("teams", {
          name,
          description: description || null,
        });

        const createdTeam = response.outputs.data?.team;

        setModal(null);
        setNotice(`Team "${name}" created successfully.`);
        setIsLoading(true);

        await loadTeams(createdTeam?.id);
      } else if (modal === "edit-team" && selectedTeam) {
        await api.patch(
          `teams/${encodeURIComponent(selectedTeam.id)}`,
          {
            name,
            description: description || null,
          },
        );

        setModal(null);
        setNotice(`Team "${name}" updated successfully.`);
        setIsLoading(true);

        await loadTeams(selectedTeam.id);
      }
    } catch (error) {
      setModalError(getErrorMessage(error));
    } finally {
      setIsSaving(false);
    }
  }

  async function addMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedTeam || !selectedAccountId || isSaving) return;

    const account = directoryAccounts.find(
      (candidate) => candidate.id === selectedAccountId,
    );

    if (!account) {
      setModalError("Select an account from the search results.");
      return;
    }

    setIsSaving(true);
    setModalError("");
    setActionError("");

    try {
      await api.post(
        `teams/${encodeURIComponent(selectedTeam.id)}/members`,
        {
          user_id: selectedAccountId,
          role: newMemberRole,
        },
      );

      setModal(null);
      setNotice(`${account.full_name} added to ${selectedTeam.name}.`);
      setMembersLoading(true);

      await loadMembers();
    } catch (error) {
      setModalError(getErrorMessage(error));
    } finally {
      setIsSaving(false);
    }
  }

  async function saveMemberRole(member: TeamMember) {
    if (!selectedTeam || savingMemberId || isSaving) return;

    const role = draftRoles[member.user_id];

    if (!role || role === member.role) return;

    setSavingMemberId(member.user_id);
    setActionError("");
    setNotice("");

    try {
      await api.patch(
        `teams/${encodeURIComponent(selectedTeam.id)}/members/${encodeURIComponent(member.user_id)}/role`,
        { role },
      );

      setNotice(`${member.full_name}'s role has been updated.`);
      setMembersLoading(true);

      await loadMembers();
    } catch (error) {
      setActionError(getErrorMessage(error));
      setDraftRoles((current) => ({
        ...current,
        [member.user_id]: member.role,
      }));
    } finally {
      setSavingMemberId(null);
    }
  }

  async function removeMember(member: TeamMember) {
    if (!selectedTeam || savingMemberId || isSaving) return;

    const confirmed = window.confirm(
      `Remove ${member.full_name} from ${selectedTeam.name}?`,
    );

    if (!confirmed) return;

    setSavingMemberId(member.user_id);
    setActionError("");
    setNotice("");

    try {
      await api.delete(
        `teams/${encodeURIComponent(selectedTeam.id)}/members/${encodeURIComponent(member.user_id)}`,
      );

      setNotice(`${member.full_name} was removed from the team.`);
      setMembersLoading(true);

      await loadMembers();
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setSavingMemberId(null);
    }
  }

  async function deleteTeam() {
    if (!selectedTeam || isSaving) return;

    const confirmed = window.confirm(
      `Delete "${selectedTeam.name}"? This action cannot be undone.`,
    );

    if (!confirmed) return;

    setIsSaving(true);
    setActionError("");
    setNotice("");

    try {
      await api.delete(`teams/${encodeURIComponent(selectedTeam.id)}`);

      const deletedName = selectedTeam.name;

      setSelectedTeamId("");
      setMembers([]);
      setMemberTotal(0);
      setNotice(`Team "${deletedName}" deleted.`);
      setIsLoading(true);
      setMembersLoading(true);

      await loadTeams();
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-[1500px] space-y-7">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 flex items-center gap-2 text-xs text-zinc-500">
            <span>Workspace</span>
            <span className="text-zinc-700">/</span>
            <span className="text-zinc-300">Teams</span>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Teams
          </h1>

          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
            Organize people, manage team responsibilities, and control who
            can participate in approval and operational workflows.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void refreshAll()}
            disabled={isLoading || isSaving}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/[0.08] px-4 text-xs font-medium text-zinc-300 hover:bg-white/[0.04] disabled:opacity-50"
          >
            <RefreshCw
              size={14}
              className={isLoading ? "animate-spin" : ""}
            />
            Refresh
          </button>

          <button
            type="button"
            onClick={openCreateTeam}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-semibold text-zinc-950 hover:bg-white"
          >
            <Plus size={15} />
            Create team
          </button>
        </div>
      </header>

      {notice && (
        <div
          role="status"
          className="flex items-center gap-3 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.05] px-4 py-3 text-sm text-emerald-200"
        >
          <CheckCircle2 size={17} />
          <span className="flex-1">{notice}</span>

          <button
            type="button"
            aria-label="Dismiss notice"
            onClick={() => setNotice("")}
          >
            <X size={15} />
          </button>
        </div>
      )}

      {pageError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-xl border border-red-400/20 bg-red-400/[0.04] px-4 py-3"
        >
          <AlertCircle size={17} className="mt-0.5 shrink-0 text-red-300" />
          <p className="flex-1 text-sm text-red-200">{pageError}</p>

          <button
            type="button"
            onClick={() => {
              setIsLoading(true);
              setPageError("");
              void loadTeams();
            }}
            className="text-xs text-zinc-300 underline underline-offset-4"
          >
            Retry
          </button>
        </div>
      )}

      {actionError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-xl border border-red-400/20 bg-red-400/[0.04] px-4 py-3"
        >
          <AlertCircle size={17} className="mt-0.5 shrink-0 text-red-300" />
          <p className="flex-1 text-sm leading-6 text-red-200">
            {actionError}
          </p>

          <button
            type="button"
            onClick={() => setActionError("")}
            aria-label="Dismiss error"
          >
            <X size={15} />
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
        {/* Team list */}
        <aside className="overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.015]">
          <div className="border-b border-white/[0.07] p-4">
            <div className="flex items-center justify-between">
              <SectionHeading
                title="Your teams"
                description={`${teams.length} accessible team${teams.length === 1 ? "" : "s"}`}
              />

              <Users size={17} className="text-zinc-500" />
            </div>

            <form
              onSubmit={(event) => {
                event.preventDefault();
                setTeamSearch(teamSearchInput.trim());
              }}
              className="relative mt-4"
            >
              <Search
                size={14}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500"
              />
              <input
                value={teamSearchInput}
                onChange={(event) => setTeamSearchInput(event.target.value)}
                placeholder="Find a team..."
                aria-label="Search your teams"
                className="h-10 w-full rounded-lg border border-white/[0.08] bg-black/20 pl-9 pr-3 text-xs outline-none placeholder:text-zinc-600 focus:border-indigo-400/50"
              />
            </form>
          </div>

          {isLoading && teams.length === 0 ? (
            <div className="space-y-3 p-4">
              {[1, 2, 3].map((item) => (
                <div
                  key={item}
                  className="h-16 animate-pulse rounded-lg bg-white/[0.035]"
                />
              ))}
            </div>
          ) : visibleTeams.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <Users size={22} className="mx-auto text-zinc-600" />

              <p className="mt-3 text-sm text-zinc-300">
                {teamSearch ? "No matching teams" : "No teams yet"}
              </p>

              <p className="mt-2 text-xs leading-5 text-zinc-500">
                {teamSearch
                  ? "Try another search."
                  : "Create a team to organize members and work items."}
              </p>
            </div>
          ) : (
            <div className="space-y-1 p-2">
              {visibleTeams.map((team) => {
                const active = team.id === selectedTeamId;

                return (
                  <button
                    type="button"
                    key={team.id}
                    onClick={() => {
                      setSelectedTeamId(team.id);
                      setMembersLoading(true);
                      setMemberError("");
                      setActionError("");
                      setMemberSearch("");
                      setMemberSearchInput("");
                    }}
                    className={[
                      "flex w-full items-start gap-3 rounded-lg border p-3 text-left transition",
                      active
                        ? "border-white/[0.09] bg-white/[0.055]"
                        : "border-transparent hover:bg-white/[0.03]",
                    ].join(" ")}
                  >
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/[0.07] bg-white/[0.025]">
                      <Users size={16} className="text-zinc-400" />
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-zinc-200">
                        {team.name}
                      </p>

                      <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-zinc-500">
                        {team.description || "No team description"}
                      </p>

                      <div className="mt-2">
                        <RoleBadge
                          role={team.membership_role ?? "member"}
                        />
                      </div>
                    </div>

                    <ArrowRight
                      size={14}
                      className={`mt-1 shrink-0 ${
                        active ? "text-zinc-300" : "text-zinc-600"
                      }`}
                    />
                  </button>
                );
              })}
            </div>
          )}
        </aside>

        {/* Selected team */}
        <main className="min-w-0 space-y-5">
          {!selectedTeam ? (
            <section className="flex min-h-80 flex-col items-center justify-center rounded-xl border border-white/[0.07] bg-white/[0.015] px-6 text-center">
              <Users size={25} className="text-zinc-500" />
              <h2 className="mt-4 text-sm font-semibold text-zinc-200">
                Select a team
              </h2>
              <p className="mt-2 max-w-sm text-xs leading-5 text-zinc-500">
                Choose a team from the left or create a new one.
              </p>
            </section>
          ) : (
            <>
              <section className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 sm:p-6">
                <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-indigo-400/10 bg-indigo-400/[0.06]">
                      <Users size={21} className="text-indigo-200" />
                    </div>

                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="break-words text-xl font-semibold text-zinc-100">
                          {selectedTeam.name}
                        </h2>
                        <RoleBadge
                          role={selectedTeam.membership_role ?? "member"}
                        />
                      </div>

                      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-zinc-400">
                        {selectedTeam.description ||
                          "This team has no description yet."}
                      </p>

                      {selectedTeam.created_at && (
                        <p className="mt-3 text-[11px] text-zinc-600">
                          Team created {formatDate(selectedTeam.created_at)}
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={openEditTeam}
                      className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs text-zinc-300 hover:bg-white/[0.04]"
                    >
                      Edit team
                    </button>

                    <button
                      type="button"
                      onClick={() => void deleteTeam()}
                      disabled={isSaving}
                      className="inline-flex h-9 items-center gap-2 rounded-lg border border-red-400/15 px-3 text-xs text-red-300 hover:bg-red-400/[0.06] disabled:opacity-50"
                    >
                      <Trash2 size={13} />
                      Delete
                    </button>
                  </div>
                </div>

                <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border border-white/[0.06] bg-white/[0.015] p-4">
                    <p className="text-[10px] uppercase tracking-wider text-zinc-600">
                      Members shown
                    </p>
                    <p className="mt-2 text-2xl font-semibold">
                      {membersLoading ? "—" : memberTotal}
                    </p>
                  </div>

                  <div className="rounded-lg border border-white/[0.06] bg-white/[0.015] p-4">
                    <p className="text-[10px] uppercase tracking-wider text-zinc-600">
                      Team leads shown
                    </p>
                    <p className="mt-2 text-2xl font-semibold">
                      {membersLoading
                        ? "—"
                        : members.filter((member) => member.role === "lead")
                            .length}
                    </p>
                  </div>

                  <div className="rounded-lg border border-white/[0.06] bg-white/[0.015] p-4">
                    <p className="text-[10px] uppercase tracking-wider text-zinc-600">
                      Approval-capable members shown
                    </p>
                    <p className="mt-2 text-2xl font-semibold">
                      {membersLoading
                        ? "—"
                        : members.filter((member) =>
                            ["lead", "approver"].includes(member.role),
                          ).length}
                    </p>
                  </div>
                </div>
              </section>

              <section className="overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.015]">
                <div className="flex flex-col justify-between gap-4 border-b border-white/[0.07] p-5 sm:flex-row sm:items-center">
                  <SectionHeading
                    title="Team members"
                    description="Manage membership and role assignments."
                  />

                  <button
                    type="button"
                    onClick={openAddMember}
                    className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-semibold text-zinc-950 hover:bg-white"
                  >
                    <UserPlus size={14} />
                    Add member
                  </button>
                </div>

                <div className="border-b border-white/[0.06] p-4">
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      setMemberSearch(memberSearchInput.trim());
                      setMembersLoading(true);
                    }}
                    className="relative"
                  >
                    <Search
                      size={14}
                      className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500"
                    />
                    <input
                      value={memberSearchInput}
                      onChange={(event) =>
                        setMemberSearchInput(event.target.value)
                      }
                      placeholder="Search members by name, email, or role..."
                      aria-label="Search team members"
                      className="h-10 w-full rounded-lg border border-white/[0.08] bg-black/20 pl-9 pr-3 text-xs outline-none placeholder:text-zinc-600 focus:border-indigo-400/50"
                    />
                  </form>
                </div>

                {memberError && (
                  <div className="flex items-start gap-3 border-b border-white/[0.06] bg-red-400/[0.035] p-4">
                    <AlertCircle
                      size={16}
                      className="mt-0.5 shrink-0 text-red-300"
                    />
                    <div className="flex-1">
                      <p className="text-xs leading-5 text-red-200">
                        {memberError}
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          setMembersLoading(true);
                          setMemberError("");
                          void loadMembers();
                        }}
                        className="mt-2 text-xs text-zinc-300 underline underline-offset-4"
                      >
                        Retry
                      </button>
                    </div>
                  </div>
                )}

                {membersLoading ? (
                  <div className="space-y-3 p-5">
                    {[1, 2, 3].map((index) => (
                      <div
                        key={index}
                        className="h-16 animate-pulse rounded-lg bg-white/[0.035]"
                      />
                    ))}
                  </div>
                ) : visibleMembers.length === 0 ? (
                  <div className="px-6 py-14 text-center">
                    <Users size={23} className="mx-auto text-zinc-600" />
                    <p className="mt-3 text-sm text-zinc-300">
                      {memberSearch
                        ? "No matching members"
                        : "No members found"}
                    </p>
                    <p className="mt-2 text-xs text-zinc-500">
                      {memberSearch
                        ? "Try another search."
                        : "This team currently has no members available to display."}
                    </p>
                  </div>
                ) : (
                  <div className="divide-y divide-white/[0.055]">
                    {visibleMembers.map((member) => {
                      const draftRole =
                        draftRoles[member.user_id] ?? member.role;

                      const roleChanged = draftRole !== member.role;

                      return (
                        <div
                          key={member.membership_id}
                          className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5"
                        >
                          <div className="flex min-w-0 items-center gap-3">
                            <Initials name={member.full_name} />

                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-zinc-200">
                                {member.full_name}
                              </p>
                              <p className="mt-1 truncate text-xs text-zinc-500">
                                {member.email}
                              </p>
                              {member.joined_at && (
                                <p className="mt-1 text-[10px] text-zinc-600">
                                  Joined {formatDate(member.joined_at)}
                                </p>
                              )}
                            </div>
                          </div>

                          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                            <div className="relative min-w-36">
                              <select
                                value={draftRole}
                                onChange={(event) =>
                                  setDraftRoles((current) => ({
                                    ...current,
                                    [member.user_id]: event.target
                                      .value as TeamRole,
                                  }))
                                }
                                aria-label={`Role for ${member.full_name}`}
                                disabled={
                                  Boolean(savingMemberId) || isSaving
                                }
                                className="h-9 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#111114] pl-3 pr-8 text-xs text-zinc-300 outline-none focus:border-indigo-400/50 disabled:opacity-50"
                              >
                                <option value="lead">Team lead</option>
                                <option value="member">Member</option>
                                <option value="approver">Approver</option>
                              </select>

                              <ChevronDown
                                size={12}
                                className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500"
                              />
                            </div>

                            <button
                              type="button"
                              onClick={() => void saveMemberRole(member)}
                              disabled={
                                !roleChanged ||
                                Boolean(savingMemberId) ||
                                isSaving
                              }
                              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-white/[0.08] px-3 text-xs text-zinc-300 hover:bg-white/[0.04] disabled:opacity-40"
                            >
                              {savingMemberId === member.user_id ? (
                                <LoaderCircle
                                  size={13}
                                  className="animate-spin"
                                />
                              ) : (
                                <CheckCircle2 size={13} />
                              )}
                              Save role
                            </button>

                            <button
                              type="button"
                              onClick={() => void removeMember(member)}
                              disabled={
                                Boolean(savingMemberId) || isSaving
                              }
                              aria-label={`Remove ${member.full_name}`}
                              title={`Remove ${member.full_name}`}
                              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-red-400/15 text-red-300 hover:bg-red-400/[0.06] disabled:opacity-40"
                            >
                              {savingMemberId === member.user_id ? (
                                <LoaderCircle
                                  size={14}
                                  className="animate-spin"
                                />
                              ) : (
                                <Trash2 size={14} />
                              )}
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {!membersLoading && memberTotal > PAGE_SIZE && (
                  <p className="border-t border-white/[0.06] px-5 py-3 text-[11px] text-zinc-500">
                    Showing the first {PAGE_SIZE} members. Refine the search
                    to locate a particular member.
                  </p>
                )}
              </section>
            </>
          )}
        </main>
      </div>

      {/* Team or member dialogs */}
      {modal && (
        <div
          className="fixed inset-0 z-[100] flex items-end justify-center bg-black/75 p-0 backdrop-blur-sm sm:items-center sm:p-5"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !isSaving) {
              setModal(null);
            }
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="team-dialog-title"
            className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-2xl border border-white/[0.09] bg-[#111114] p-5 shadow-2xl shadow-black/50 sm:rounded-2xl sm:p-7"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.17em] text-zinc-500">
                  Team management
                </p>

                <h2
                  id="team-dialog-title"
                  className="mt-2 text-xl font-semibold text-zinc-100"
                >
                  {modal === "create-team"
                    ? "Create team"
                    : modal === "edit-team"
                      ? "Edit team"
                      : "Add a team member"}
                </h2>

                <p className="mt-2 text-xs leading-5 text-zinc-500">
                  {modal === "add-member"
                    ? `Find an existing active account to add to ${selectedTeam?.name ?? "the team"}.`
                    : "Keep the team information clear and easy for members to recognize."}
                </p>
              </div>

              <button
                type="button"
                aria-label="Close dialog"
                disabled={isSaving}
                onClick={() => setModal(null)}
                className="rounded-lg p-2 text-zinc-500 hover:bg-white/[0.05] hover:text-white disabled:opacity-50"
              >
                <X size={18} />
              </button>
            </div>

            {modal === "add-member" ? (
              <div className="mt-6 space-y-5">
                <form onSubmit={searchAccounts} className="space-y-3">
                  <label
                    htmlFor="account-search"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Find account by name or email
                  </label>

                  <div className="flex gap-2">
                    <input
                      id="account-search"
                      value={directoryQuery}
                      onChange={(event) =>
                        setDirectoryQuery(event.target.value)
                      }
                      required
                      placeholder="Name or email address"
                      className="h-10 min-w-0 flex-1 rounded-lg border border-white/[0.08] bg-white/[0.025] px-3 text-sm outline-none placeholder:text-zinc-600 focus:border-indigo-400/50"
                    />

                    <button
                      type="submit"
                      disabled={directoryLoading || isSaving}
                      className="inline-flex h-10 items-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs text-zinc-200 hover:bg-white/[0.04] disabled:opacity-50"
                    >
                      {directoryLoading ? (
                        <LoaderCircle
                          size={13}
                          className="animate-spin"
                        />
                      ) : (
                        <Search size={13} />
                      )}
                      Search
                    </button>
                  </div>
                </form>

                {directoryError && (
                  <p
                    role="alert"
                    className="rounded-lg border border-amber-400/20 bg-amber-400/[0.04] p-3 text-xs leading-5 text-amber-200"
                  >
                    {directoryError}
                  </p>
                )}

                {directoryAccounts.length > 0 && (
                  <div className="max-h-60 space-y-1 overflow-y-auto rounded-lg border border-white/[0.07] p-2">
                    {directoryAccounts.map((account) => (
                      <button
                        type="button"
                        key={account.id}
                        onClick={() => setSelectedAccountId(account.id)}
                        className={[
                          "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition",
                          selectedAccountId === account.id
                            ? "border-indigo-400/25 bg-indigo-400/[0.07]"
                            : "border-transparent hover:bg-white/[0.035]",
                        ].join(" ")}
                      >
                        <Initials name={account.full_name} />

                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs font-medium text-zinc-200">
                            {account.full_name}
                          </p>
                          <p className="mt-1 truncate text-[11px] text-zinc-500">
                            {account.email}
                          </p>
                        </div>

                        {selectedAccountId === account.id && (
                          <CheckCircle2
                            size={16}
                            className="text-indigo-300"
                          />
                        )}
                      </button>
                    ))}
                  </div>
                )}

                <div className="space-y-2">
                  <label
                    htmlFor="new-member-role"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Team role
                  </label>

                  <div className="relative">
                    <select
                      id="new-member-role"
                      value={newMemberRole}
                      onChange={(event) =>
                        setNewMemberRole(event.target.value as TeamRole)
                      }
                      disabled={isSaving}
                      className="h-11 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#17171b] px-3 pr-9 text-sm outline-none focus:border-indigo-400/50 disabled:opacity-50"
                    >
                      <option value="member">Member</option>
                      <option value="approver">Approver</option>
                      <option value="lead">Team lead</option>
                    </select>

                    <ChevronDown
                      size={14}
                      className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
                    />
                  </div>

                  <p className="text-[10px] leading-5 text-zinc-600">
                    The backend determines whether your role permits adding
                    members or assigning this role.
                  </p>
                </div>

                {modalError && (
                  <p
                    role="alert"
                    className="rounded-lg border border-red-400/20 bg-red-400/[0.05] p-3 text-xs leading-5 text-red-300"
                  >
                    {modalError}
                  </p>
                )}

                <div className="flex flex-col-reverse gap-2 border-t border-white/[0.07] pt-4 sm:flex-row sm:justify-end">
                  <button
                    type="button"
                    disabled={isSaving}
                    onClick={() => setModal(null)}
                    className="h-10 rounded-lg border border-white/[0.08] px-4 text-xs text-zinc-300 hover:bg-white/[0.04] disabled:opacity-50"
                  >
                    Cancel
                  </button>

                  <button
                    type="button"
                    disabled={!selectedAccountId || isSaving}
                    onClick={() => {
                      const fakeEvent = {
                        preventDefault() {},
                      } as FormEvent<HTMLFormElement>;

                      void addMember(fakeEvent);
                    }}
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-semibold text-zinc-950 hover:bg-white disabled:opacity-50"
                  >
                    {isSaving ? (
                      <LoaderCircle size={14} className="animate-spin" />
                    ) : (
                      <UserPlus size={14} />
                    )}
                    Add member
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={saveTeam} className="mt-6 space-y-5">
                <div className="space-y-2">
                  <label
                    htmlFor="team-name"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Team name
                  </label>

                  <input
                    id="team-name"
                    value={draftName}
                    onChange={(event) => setDraftName(event.target.value)}
                    required
                    maxLength={100}
                    disabled={isSaving}
                    placeholder="e.g. Operations"
                    className="h-11 w-full rounded-lg border border-white/[0.08] bg-white/[0.025] px-3.5 text-sm outline-none placeholder:text-zinc-600 focus:border-indigo-400/50 disabled:opacity-50"
                  />

                  <p className="text-right text-[10px] text-zinc-600">
                    {draftName.length}/100
                  </p>
                </div>

                <div className="space-y-2">
                  <label
                    htmlFor="team-description"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Description
                    <span className="ml-1 font-normal text-zinc-600">
                      (optional)
                    </span>
                  </label>

                  <textarea
                    id="team-description"
                    value={draftDescription}
                    onChange={(event) =>
                      setDraftDescription(event.target.value)
                    }
                    rows={4}
                    disabled={isSaving}
                    placeholder="Describe the team's responsibilities..."
                    className="w-full resize-y rounded-lg border border-white/[0.08] bg-white/[0.025] px-3.5 py-3 text-sm leading-6 outline-none placeholder:text-zinc-600 focus:border-indigo-400/50 disabled:opacity-50"
                  />
                </div>

                {modalError && (
                  <p
                    role="alert"
                    className="rounded-lg border border-red-400/20 bg-red-400/[0.05] p-3 text-xs leading-5 text-red-300"
                  >
                    {modalError}
                  </p>
                )}

                <div className="flex flex-col-reverse gap-2 border-t border-white/[0.07] pt-4 sm:flex-row sm:justify-end">
                  <button
                    type="button"
                    onClick={() => setModal(null)}
                    disabled={isSaving}
                    className="h-10 rounded-lg border border-white/[0.08] px-4 text-xs text-zinc-300 hover:bg-white/[0.04] disabled:opacity-50"
                  >
                    Cancel
                  </button>

                  <button
                    type="submit"
                    disabled={isSaving || !draftName.trim()}
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-semibold text-zinc-950 hover:bg-white disabled:opacity-50"
                  >
                    {isSaving ? (
                      <LoaderCircle size={14} className="animate-spin" />
                    ) : (
                      <Plus size={14} />
                    )}
                    {modal === "create-team" ? "Create team" : "Save changes"}
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>
      )}
    </div>
  );
}