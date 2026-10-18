"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  FileText,
  History,
  LoaderCircle,
  MessageSquare,
  RefreshCw,
  Save,
  ShieldCheck,
  UserRound,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { api, ApiError, type ServiceResponse } from "@/lib/api-client";
import { useAuth } from "@/providers/auth-provider";

type WorkStatus =
  | "open"
  | "in_progress"
  | "pending_approval"
  | "resolved"
  | "cancelled";

type WorkPriority = "low" | "medium" | "high" | "critical";
type WorkType = "investigation" | "action" | "incident" | "approval";

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

interface WorkItemEnvelope {
  work_item: WorkItem;
}

interface PageData<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

interface TeamEnvelope {
  team: {
    id: string;
    name: string;
    description?: string | null;
    created_by: string;
  };
}

interface TeamMember {
  membership_id?: string;
  team_id: string;
  user_id: string;
  role: string;
  full_name: string;
  email: string;
  account_status?: string;
}

interface ActivityItem {
  id: string;
  work_item_id: string;
  actor_id?: string;
  actor_user_id?: string;
  action: string;
  details?: Record<string, unknown> | null;
  created_at: string;
}

interface ApprovalItem {
  id: string;
  work_item_id: string;
  requested_by: string;
  approver_id: string | null;
  status: string;
  decision_reason?: string | null;
  requested_at: string;
  decided_at?: string | null;
  requester_name?: string;
  approver_name?: string | null;
}

type LoadResult<T> = {
  data: T | null;
  error: unknown | null;
};

type ActionName =
  | "save"
  | "claim"
  | "assign"
  | "status"
  | "priority"
  | "approval"
  | "note";

const PRIORITIES: WorkPriority[] = [
  "low",
  "medium",
  "high",
  "critical",
];

const TYPES: WorkType[] = [
  "investigation",
  "action",
  "incident",
  "approval",
];

const ALLOWED_TRANSITIONS: Record<WorkStatus, WorkStatus[]> = {
  open: ["in_progress", "cancelled"],
  in_progress: ["open", "resolved", "cancelled"],
  pending_approval: ["cancelled"],
  resolved: ["in_progress"],
  cancelled: [],
};

// ============================================================
// HELPERS
// ============================================================

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
    case "open":
      return "border-slate-400/20 bg-slate-400/[0.07] text-slate-300";
    case "in_progress":
      return "border-blue-400/20 bg-blue-400/[0.07] text-blue-300";
    case "pending_approval":
    case "pending":
      return "border-amber-400/20 bg-amber-400/[0.07] text-amber-300";
    case "resolved":
    case "approved":
      return "border-emerald-400/20 bg-emerald-400/[0.07] text-emerald-300";
    case "cancelled":
    case "rejected":
      return "border-red-400/20 bg-red-400/[0.07] text-red-300";
    default:
      return "border-white/10 bg-white/[0.03] text-zinc-400";
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
      return "Unable to reach the API. Check that the backend is running.";
    }

    if (error.status === 401) {
      return "Your session could not be verified. Please sign in again.";
    }

    if (error.status === 403) {
      return "You do not have permission to perform this operation.";
    }

    if (error.status === 409) {
      return (
        error.message ||
        "The item changed or its workflow state no longer allows this action."
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

function activityDescription(action: string): string {
  const descriptions: Record<string, string> = {
    work_item_created: "Work item created",
    work_item_updated: "Work item details updated",
    work_item_claimed: "Work item claimed",
    work_item_assigned: "Assignment changed",
    work_item_status_changed: "Status changed",
    work_item_priority_changed: "Priority changed",
    approval_requested: "Approval requested",
    approval_approver_assigned: "Approver assigned",
    approval_approved: "Approval approved",
    approval_rejected: "Approval rejected",
    note_added: "Progress note added",
    approval_retried: "Approval request retried",
  };

  return descriptions[action] ?? label(action);
}

function getPersonName(
  id: string | null | undefined,
  members: TeamMember[],
  currentUserId?: string,
  currentUserName?: string,
): string {
  if (!id) return "Unassigned";

  if (id === currentUserId && currentUserName) {
    return currentUserName;
  }

  return (
    members.find((member) => member.user_id === id)?.full_name ??
    "Former team member"
  );
}

function isEligibleMember(member: TeamMember): boolean {
  const active =
    member.account_status === undefined ||
    member.account_status === "active";

  return (
    active &&
    ["lead", "approver"].includes(member.role)
  );
}

function sortApprovers(members: TeamMember[]): TeamMember[] {
  return [...members].sort((a, b) => {
    const roleRank = (role: string) =>
      role === "lead" ? 0 : 1;

    return (
      roleRank(a.role) - roleRank(b.role) ||
      a.full_name.localeCompare(b.full_name)
    );
  });
}

function getPreferredApprover(
  members: TeamMember[],
): TeamMember | null {
  const ordered = sortApprovers(members);

  return ordered.find((member) => member.role === "lead") ??
    ordered[0] ??
    null;
}

function getActivityNote(
  details?: Record<string, unknown> | null,
): string | null {
  const note = details?.note;

  return typeof note === "string" && note.trim().length > 0
    ? note
    : null;
}

function getVisibleActivityDetails(
  details: Record<string, unknown> | null | undefined,
  members: TeamMember[],
  teamId: string,
  teamName: string,
  currentUserId?: string,
  currentUserName?: string,
): Array<{ label: string; value: string }> {
  if (!details) return [];

  const visible: Array<{ label: string; value: string }> = [];

  for (const [key, rawValue] of Object.entries(details)) {
    if (key === "note" || rawValue == null) continue;

    if (
      typeof rawValue !== "string" &&
      typeof rawValue !== "number" &&
      typeof rawValue !== "boolean"
    ) {
      continue;
    }

    let value = String(rawValue);

    if (
      typeof rawValue === "string" &&
      /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(rawValue)
    ) {
      if (rawValue === teamId) {
        value = teamName;
      } else {
        const member = members.find(
          (candidate) => candidate.user_id === rawValue,
        );

        if (member) {
          value = member.full_name;
        } else if (
          rawValue === currentUserId &&
          currentUserName
        ) {
          value = currentUserName;
        } else {
          continue;
        }
      }
    }

    visible.push({
      label: label(key.replace(/_id$/i, "")),
      value,
    });
  }

  return visible;
}

// ============================================================
// REUSABLE UI
// ============================================================

function SelectField({
  labelText,
  value,
  onChange,
  options,
  disabled = false,
}: {
  labelText: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly string[];
  disabled?: boolean;
}) {
  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-zinc-400">
        {labelText}
      </label>

      <div className="relative">
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          className="h-10 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#121216] px-3 pr-9 text-xs text-zinc-200 outline-none focus:border-indigo-400/50 disabled:opacity-50"
        >
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
    </div>
  );
}

function MemberSelectField({
  members,
  value,
  onChange,
  disabled = false,
  id = "approver-select",
}: {
  members: TeamMember[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <div className="space-y-2">
      <label
        htmlFor={id}
        className="block text-xs font-medium text-zinc-400"
      >
        Approver
      </label>

      <div className="relative">
        <select
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled || members.length === 0}
          className="h-11 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#121216] px-3 pr-9 text-sm text-zinc-200 outline-none focus:border-indigo-400/50 disabled:opacity-50"
        >
          <option value="">Select an eligible approver</option>

          {members.map((member) => (
            <option key={member.user_id} value={member.user_id}>
              {member.full_name} —{" "}
              {member.role === "lead" ? "Team lead" : "Approver"}
              {member.email ? ` · ${member.email}` : ""}
            </option>
          ))}
        </select>

        <ChevronDown
          size={14}
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
        />
      </div>
    </div>
  );
}

function SectionHeading({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/[0.07] bg-white/[0.025]">
        <Icon size={16} className="text-zinc-400" />
      </div>

      <div>
        <h2 className="text-sm font-semibold text-zinc-100">
          {title}
        </h2>

        {description && (
          <p className="mt-1 text-xs leading-5 text-zinc-500">
            {description}
          </p>
        )}
      </div>
    </div>
  );
}

// ============================================================
// PAGE
// ============================================================

export default function WorkItemDetailPage() {
  const params = useParams<{ work_item_id: string }>();
  const workItemId = params.work_item_id;
  const { user } = useAuth();

  const [item, setItem] = useState<WorkItem | null>(null);
  const [teamName, setTeamName] = useState("Loading team...");
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState<ActionName | null>(null);

  const [pageError, setPageError] = useState("");
  const [relatedError, setRelatedError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");

  const [editMode, setEditMode] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [draftType, setDraftType] =
    useState<WorkType>("investigation");

  const [selectedAssignee, setSelectedAssignee] = useState("");
  const [selectedStatus, setSelectedStatus] =
    useState<WorkStatus>("open");
  const [selectedPriority, setSelectedPriority] =
    useState<WorkPriority>("medium");

  const [note, setNote] = useState("");

  const [approvalDialogOpen, setApprovalDialogOpen] = useState(false);
  const [selectedApproverId, setSelectedApproverId] = useState("");
  const [approvalDialogError, setApprovalDialogError] = useState("");

  const [assignmentSelections, setAssignmentSelections] =
    useState<Record<string, string>>({});

  const requestVersion = useRef(0);

  const loadAll = useCallback(async () => {
    const version = ++requestVersion.current;

    try {
      const response = await api.get<WorkItemEnvelope>(
        `work-items/${encodeURIComponent(workItemId)}`,
      );

      const currentItem = response.outputs.data?.work_item;

      if (!currentItem) {
        throw new Error("The API returned no work-item details.");
      }

      if (version !== requestVersion.current) return;

      setPageError("");
      setRelatedError("");
      setItem(currentItem);
      setDraftTitle(currentItem.title);
      setDraftDescription(currentItem.description);
      setDraftType(currentItem.type);
      setSelectedAssignee(currentItem.assignee_id ?? "");
      setSelectedStatus(currentItem.status);
      setSelectedPriority(currentItem.priority);

      const [
        teamResult,
        activityResult,
        approvalResult,
        memberResult,
      ] = await Promise.all([
        loadSafely(
          api.get<TeamEnvelope>(
            `teams/${encodeURIComponent(currentItem.team_id)}`,
          ),
        ),
        loadSafely(
          api.get<PageData<ActivityItem>>(
            `work-items/${encodeURIComponent(workItemId)}/activity`,
            { query: { limit: 20, offset: 0 } },
          ),
        ),
        loadSafely(
          api.get<PageData<ApprovalItem>>(
            `work-items/${encodeURIComponent(workItemId)}/approvals`,
            { query: { limit: 10, offset: 0 } },
          ),
        ),
        loadSafely(
          api.get<PageData<TeamMember>>(
            `teams/${encodeURIComponent(currentItem.team_id)}/members`,
            { query: { limit: 100, offset: 0 } },
          ),
        ),
      ]);

      if (version !== requestVersion.current) return;

      setTeamName(teamResult.data?.team?.name ?? "Team unavailable");
      setActivities(activityResult.data?.items ?? []);
      setApprovals(approvalResult.data?.items ?? []);

      const activeMembers = (memberResult.data?.items ?? []).filter(
        (member) =>
          member.account_status === undefined ||
          member.account_status === "active",
      );

      setMembers(activeMembers);

      const failedSections = [
        teamResult.error ? "team details" : null,
        activityResult.error ? "activity history" : null,
        approvalResult.error ? "approval history" : null,
        memberResult.error ? "team members" : null,
      ].filter(Boolean);

      if (failedSections.length > 0) {
        setRelatedError(
          `Some sections could not be loaded: ${failedSections.join(", ")}.`,
        );
      }
    } catch (error) {
      if (version !== requestVersion.current) return;
      setPageError(getErrorMessage(error));
    } finally {
      if (version === requestVersion.current) {
        setIsLoading(false);
      }
    }
  }, [workItemId]);

  useEffect(() => {
    void loadAll();

    return () => {
      requestVersion.current += 1;
    };
  }, [loadAll]);

  const eligibleApprovers = sortApprovers(
    members.filter(
      (member) =>
        isEligibleMember(member) &&
        member.user_id !== user?.id,
    ),
  );

  const defaultApprover = getPreferredApprover(eligibleApprovers);

  function getApproversForRequest(
    approval: ApprovalItem,
  ): TeamMember[] {
    return sortApprovers(
      members.filter(
        (member) =>
          isEligibleMember(member) &&
          member.user_id !== approval.requested_by,
      ),
    );
  }

  function refreshItem() {
    setIsLoading(true);
    setPageError("");
    setRelatedError("");
    setActionError("");
    void loadAll();
  }

  async function runAction(
    action: ActionName,
    successMessage: string,
    operation: () => Promise<unknown>,
  ) {
    if (isSaving) return;

    setIsSaving(action);
    setActionError("");
    setNotice("");

    try {
      await operation();

      setNotice(successMessage);
      setEditMode(false);
      setIsLoading(true);

      await loadAll();
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setIsSaving(null);
    }
  }

  // ----------------------------------------------------------
  // Save work-item details
  // ----------------------------------------------------------

  async function saveDetails(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!item) return;

    const body: Record<string, string> = {
      expected_updated_at: item.updated_at,
    };

    if (draftTitle.trim() !== item.title) {
      body.title = draftTitle.trim();
    }

    if (draftDescription.trim() !== item.description) {
      body.description = draftDescription.trim();
    }

    if (draftType !== item.type) {
      body.type = draftType;
    }

    if (Object.keys(body).length === 1) {
      setEditMode(false);
      setNotice("No details were changed.");
      return;
    }

    await runAction(
      "save",
      "Work-item details updated.",
      () =>
        api.patch(
          `work-items/${encodeURIComponent(item.id)}`,
          body,
        ),
    );
  }

  // ----------------------------------------------------------
  // Claim work
  // ----------------------------------------------------------

  async function claimItem() {
    if (!item) return;

    await runAction(
      "claim",
      "Work item claimed successfully.",
      () =>
        api.post(
          `work-items/${encodeURIComponent(item.id)}/claim`,
          { expected_updated_at: item.updated_at },
        ),
    );
  }

  // ----------------------------------------------------------
  // Assignment
  // ----------------------------------------------------------

  async function saveAssignment() {
    if (!item) return;

    await runAction(
      "assign",
      "Assignment updated.",
      () =>
        api.patch(
          `work-items/${encodeURIComponent(item.id)}/assignee`,
          {
            assignee_id: selectedAssignee || null,
            expected_updated_at: item.updated_at,
          },
        ),
    );
  }

  // ----------------------------------------------------------
  // Status
  // ----------------------------------------------------------

  async function saveStatus() {
    if (!item || selectedStatus === item.status) return;

    await runAction(
      "status",
      "Work-item status updated.",
      () =>
        api.patch(
          `work-items/${encodeURIComponent(item.id)}/status`,
          {
            status: selectedStatus,
            expected_updated_at: item.updated_at,
          },
        ),
    );
  }

  // ----------------------------------------------------------
  // Priority
  // ----------------------------------------------------------

  async function savePriority() {
    if (!item || selectedPriority === item.priority) return;

    await runAction(
      "priority",
      "Work-item priority updated.",
      () =>
        api.patch(
          `work-items/${encodeURIComponent(item.id)}/priority`,
          {
            priority: selectedPriority,
            expected_updated_at: item.updated_at,
          },
        ),
    );
  }

  // ----------------------------------------------------------
  // Approval request: default to the team lead, with selection
  // ----------------------------------------------------------

  function openApprovalDialog() {
    setActionError("");
    setApprovalDialogError("");
    setSelectedApproverId(defaultApprover?.user_id ?? "");
    setApprovalDialogOpen(true);
  }

  async function submitApprovalRequest(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    if (!item || isSaving) return;

    if (!selectedApproverId) {
      setApprovalDialogError(
        "Select an eligible team lead or approver before submitting.",
      );
      return;
    }

    if (selectedApproverId === user?.id) {
      setApprovalDialogError(
        "You cannot approve your own request. Select another eligible team member.",
      );
      return;
    }

    const selectedApprover = eligibleApprovers.find(
      (member) => member.user_id === selectedApproverId,
    );

    if (!selectedApprover) {
      setApprovalDialogError(
        "That person is no longer an eligible approver. Refresh the page and try again.",
      );
      return;
    }

    setIsSaving("approval");
    setApprovalDialogError("");
    setActionError("");
    setNotice("");

    try {
      await api.post(
        `work-items/${encodeURIComponent(item.id)}/approvals`,
        {
          approver_id: selectedApproverId,
        },
      );

      setApprovalDialogOpen(false);
      setSelectedApproverId("");
      setNotice(
        `Approval request submitted to ${selectedApprover.full_name}.`,
      );

      setIsLoading(true);
      await loadAll();
    } catch (error) {
      setApprovalDialogError(getErrorMessage(error));
    } finally {
      setIsSaving(null);
    }
  }

  // ----------------------------------------------------------
  // Assign the approver on an existing pending request
  // ----------------------------------------------------------

  async function assignExistingApproval(approval: ApprovalItem) {
    if (isSaving) return;

    const candidates = getApproversForRequest(approval);

    const targetId =
      assignmentSelections[approval.id] ??
      getPreferredApprover(candidates)?.user_id ??
      "";

    if (!targetId) {
      setActionError(
        "No eligible approver is available. Add another active team lead or designated approver to this team.",
      );
      return;
    }

    if (targetId === approval.requested_by) {
      setActionError(
        "The requester cannot be their own approver.",
      );
      return;
    }

    if (!candidates.some((member) => member.user_id === targetId)) {
      setActionError(
        "The selected approver is not an eligible member of this team.",
      );
      return;
    }

    const target = candidates.find(
      (member) => member.user_id === targetId,
    );

    setIsSaving("approval");
    setActionError("");
    setNotice("");

    try {
      await api.patch(
        `approvals/${encodeURIComponent(approval.id)}/approver`,
        {
          approver_id: targetId,
        },
      );

      setNotice(
        `Approver assigned to ${target?.full_name ?? "the selected team member"}.`,
      );

      setIsLoading(true);
      await loadAll();
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setIsSaving(null);
    }
  }

  // ----------------------------------------------------------
  // Add a progress note
  // ----------------------------------------------------------

  async function addNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!item || !note.trim()) return;

    const noteText = note.trim();

    await runAction(
      "note",
      "Progress note added.",
      async () => {
        await api.post(
          `work-items/${encodeURIComponent(item.id)}/notes`,
          { note: noteText },
        );

        setNote("");
      },
    );
  }

  const allowedNextStatuses = item
    ? ALLOWED_TRANSITIONS[item.status]
    : [];

  const changedStatus = item !== null && selectedStatus !== item.status;

  const changedPriority =
    item !== null && selectedPriority !== item.priority;

  const changedAssignee =
    item !== null &&
    selectedAssignee !== (item.assignee_id ?? "");

  if (isLoading && !item) {
    return (
      <main className="flex min-h-[60vh] items-center justify-center">
        <div className="flex flex-col items-center gap-4" role="status">
          <LoaderCircle
            size={24}
            className="animate-spin text-zinc-400"
          />
          <p className="text-xs text-zinc-500">
            Loading work item...
          </p>
        </div>
      </main>
    );
  }

  if (!item) {
    return (
      <main className="mx-auto max-w-2xl py-16 text-center">
        <AlertCircle size={28} className="mx-auto text-red-300" />

        <h1 className="mt-4 text-xl font-semibold">
          Unable to load work item
        </h1>

        <p className="mt-3 text-sm leading-6 text-zinc-400">
          {pageError || "The requested item could not be loaded."}
        </p>

        <div className="mt-6 flex justify-center gap-3">
          <button
            type="button"
            onClick={refreshItem}
            className="rounded-lg border border-white/10 px-4 py-2 text-xs text-zinc-200 hover:bg-white/[0.04]"
          >
            Try again
          </button>

          <Link
            href="/work-items"
            className="rounded-lg bg-zinc-100 px-4 py-2 text-xs font-semibold text-zinc-950 hover:bg-white"
          >
            Back to work items
          </Link>
        </div>
      </main>
    );
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          href="/work-items"
          className="inline-flex items-center gap-2 text-xs text-zinc-400 transition hover:text-white"
        >
          <ArrowLeft size={14} />
          Back to work items
        </Link>

        <button
          type="button"
          onClick={refreshItem}
          disabled={isLoading || Boolean(isSaving)}
          className="inline-flex items-center gap-2 rounded-lg border border-white/[0.08] px-3 py-2 text-xs text-zinc-400 transition hover:bg-white/[0.04] hover:text-white disabled:opacity-50"
        >
          <RefreshCw
            size={13}
            className={isLoading ? "animate-spin" : ""}
          />
          Refresh
        </button>
      </div>

      <header className="flex flex-col justify-between gap-5 border-b border-white/[0.07] pb-6 xl:flex-row xl:items-start">
        <div className="min-w-0 flex-1">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span
              className={`rounded-md border px-2.5 py-1 text-[10px] font-medium ${statusClasses(item.status)}`}
            >
              {label(item.status)}
            </span>

            <span className="rounded-md border border-white/[0.08] px-2.5 py-1 text-[10px] text-zinc-400">
              {label(item.type)}
            </span>

            <span
              className={`text-[11px] ${priorityClasses(item.priority)}`}
            >
              {label(item.priority)} priority
            </span>
          </div>

          <p className="mb-2 text-[10px] uppercase tracking-[0.16em] text-zinc-600">
            Work item
          </p>

          <h1 className="break-words text-2xl font-semibold tracking-tight text-zinc-100 sm:text-3xl">
            {item.title}
          </h1>

          <p className="mt-3 max-w-3xl whitespace-pre-wrap text-sm leading-7 text-zinc-400">
            {item.description}
          </p>

          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-[11px] text-zinc-500">
            <span>Team: {teamName}</span>
            <span>Created {formatDate(item.created_at)}</span>
            <span>Last updated {formatDate(item.updated_at)}</span>

            {item.completed_at && (
              <span>Completed {formatDate(item.completed_at)}</span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap gap-2">
          {!item.assignee_id &&
            ["open", "in_progress"].includes(item.status) && (
              <button
                type="button"
                onClick={() => void claimItem()}
                disabled={Boolean(isSaving) || isLoading}
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-semibold text-zinc-950 hover:bg-white disabled:opacity-50"
              >
                {isSaving === "claim" ? (
                  <LoaderCircle size={14} className="animate-spin" />
                ) : (
                  <UserRound size={14} />
                )}
                Claim work
              </button>
            )}

          {item.status === "in_progress" && (
            <button
              type="button"
              onClick={openApprovalDialog}
              disabled={Boolean(isSaving) || isLoading}
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-amber-400/20 bg-amber-400/[0.05] px-4 text-xs font-medium text-amber-200 hover:bg-amber-400/[0.1] disabled:opacity-50"
            >
              <ShieldCheck size={14} />
              Request approval
            </button>
          )}
        </div>
      </header>

      {/* Feedback */}
      {notice && (
        <div
          role="status"
          className="flex items-center gap-3 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.04] px-4 py-3 text-sm text-emerald-200"
        >
          <CheckCircle2 size={17} />
          <span className="flex-1">{notice}</span>

          <button
            type="button"
            onClick={() => setNotice("")}
            aria-label="Dismiss notification"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {pageError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-xl border border-amber-400/20 bg-amber-400/[0.04] p-4"
        >
          <AlertCircle
            size={17}
            className="mt-0.5 shrink-0 text-amber-300"
          />

          <div className="flex-1">
            <p className="text-sm text-zinc-200">
              Refresh failed. The displayed work item may be out of date.
            </p>
            <p className="mt-1 text-xs leading-5 text-zinc-400">
              {pageError}
            </p>
            <button
              type="button"
              onClick={refreshItem}
              className="mt-2 text-xs text-zinc-300 underline underline-offset-4"
            >
              Reload latest version
            </button>
          </div>
        </div>
      )}

      {actionError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-xl border border-red-400/20 bg-red-400/[0.04] p-4"
        >
          <AlertCircle
            size={17}
            className="mt-0.5 shrink-0 text-red-300"
          />

          <div className="flex-1">
            <p className="text-sm text-red-200">{actionError}</p>

            <button
              type="button"
              onClick={() => {
                setActionError("");
                void loadAll();
              }}
              className="mt-2 text-xs text-zinc-300 underline underline-offset-4"
            >
              Refresh work item
            </button>
          </div>
        </div>
      )}

      {relatedError && (
        <div className="rounded-lg border border-amber-400/20 bg-amber-400/[0.035] px-4 py-3 text-xs leading-5 text-amber-200">
          {relatedError}
        </div>
      )}

      {/* Main content */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(340px,0.8fr)]">
        <div className="space-y-5">
          {/* Details */}
          <section className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 sm:p-6">
            <div className="flex items-start justify-between gap-4">
              <SectionHeading
                icon={FileText}
                title="Work-item details"
                description="Update the information used to investigate and resolve this item."
              />

              {!editMode && (
                <button
                  type="button"
                  onClick={() => {
                    setDraftTitle(item.title);
                    setDraftDescription(item.description);
                    setDraftType(item.type);
                    setActionError("");
                    setEditMode(true);
                  }}
                  className="shrink-0 rounded-lg border border-white/[0.08] px-3 py-2 text-xs text-zinc-300 hover:bg-white/[0.04]"
                >
                  Edit details
                </button>
              )}
            </div>

            {editMode ? (
              <form onSubmit={saveDetails} className="mt-6 space-y-4">
                <div className="space-y-2">
                  <label
                    htmlFor="detail-title"
                    className="block text-xs font-medium text-zinc-400"
                  >
                    Title
                  </label>
                  <input
                    id="detail-title"
                    value={draftTitle}
                    onChange={(event) => setDraftTitle(event.target.value)}
                    required
                    maxLength={200}
                    disabled={Boolean(isSaving)}
                    className="h-11 w-full rounded-lg border border-white/[0.08] bg-[#111114] px-3 text-sm outline-none focus:border-indigo-400/50 disabled:opacity-50"
                  />
                </div>

                <div className="space-y-2">
                  <label
                    htmlFor="detail-description"
                    className="block text-xs font-medium text-zinc-400"
                  >
                    Description
                  </label>
                  <textarea
                    id="detail-description"
                    value={draftDescription}
                    onChange={(event) =>
                      setDraftDescription(event.target.value)
                    }
                    required
                    rows={5}
                    disabled={Boolean(isSaving)}
                    className="w-full resize-y rounded-lg border border-white/[0.08] bg-[#111114] px-3 py-3 text-sm leading-6 outline-none focus:border-indigo-400/50 disabled:opacity-50"
                  />
                </div>

                <SelectField
                  labelText="Type"
                  value={draftType}
                  onChange={(value) => setDraftType(value as WorkType)}
                  options={TYPES}
                  disabled={Boolean(isSaving)}
                />

                <div className="flex flex-wrap justify-end gap-2 border-t border-white/[0.06] pt-4">
                  <button
                    type="button"
                    onClick={() => {
                      setEditMode(false);
                      setDraftTitle(item.title);
                      setDraftDescription(item.description);
                      setDraftType(item.type);
                    }}
                    disabled={Boolean(isSaving)}
                    className="h-10 rounded-lg border border-white/[0.08] px-4 text-xs text-zinc-300 hover:bg-white/[0.04] disabled:opacity-50"
                  >
                    Cancel
                  </button>

                  <button
                    type="submit"
                    disabled={
                      Boolean(isSaving) ||
                      !draftTitle.trim() ||
                      !draftDescription.trim()
                    }
                    className="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-semibold text-zinc-950 hover:bg-white disabled:opacity-50"
                  >
                    {isSaving === "save" ? (
                      <LoaderCircle size={14} className="animate-spin" />
                    ) : (
                      <Save size={14} />
                    )}
                    Save changes
                  </button>
                </div>
              </form>
            ) : (
              <div className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-zinc-600">
                    Team
                  </p>
                  <p className="mt-2 text-sm text-zinc-300">
                    {teamName}
                  </p>
                </div>

                <div>
                  <p className="text-[10px] uppercase tracking-wider text-zinc-600">
                    Created by
                  </p>
                  <p className="mt-2 text-sm text-zinc-300">
                    {getPersonName(
                      item.created_by,
                      members,
                      user?.id,
                      user?.full_name,
                    )}
                  </p>
                </div>

                <div>
                  <p className="text-[10px] uppercase tracking-wider text-zinc-600">
                    Assigned to
                  </p>
                  <p className="mt-2 text-sm text-zinc-300">
                    {getPersonName(
                      item.assignee_id,
                      members,
                      user?.id,
                      user?.full_name,
                    )}
                  </p>
                </div>

                <div>
                  <p className="text-[10px] uppercase tracking-wider text-zinc-600">
                    Work type
                  </p>
                  <p className="mt-2 text-sm text-zinc-300">
                    {label(item.type)}
                  </p>
                </div>
              </div>
            )}
          </section>

          {/* Activity history */}
          <section className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 sm:p-6">
            <SectionHeading
              icon={History}
              title="Activity history"
              description="A record of changes and decisions associated with this work item."
            />

            <div className="mt-6">
              {activities.length === 0 ? (
                <div className="rounded-lg border border-white/[0.06] bg-white/[0.015] px-4 py-8 text-center">
                  <Activity size={21} className="mx-auto text-zinc-500" />
                  <p className="mt-3 text-xs text-zinc-400">
                    No activity records are available.
                  </p>
                </div>
              ) : (
                <div className="relative space-y-0">
                  <div
                    aria-hidden="true"
                    className="absolute bottom-5 left-[15px] top-5 w-px bg-white/[0.07]"
                  />

                  {activities.map((activity) => {
                    const noteText = getActivityNote(activity.details);
                    const detailRows = getVisibleActivityDetails(
                      activity.details,
                      members,
                      item.team_id,
                      teamName,
                      user?.id,
                      user?.full_name,
                    );

                    return (
                      <article
                        key={activity.id}
                        className="relative flex gap-3 pb-6 last:pb-0"
                      >
                        <div className="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/[0.08] bg-[#111114]">
                          <Activity size={14} className="text-zinc-400" />
                        </div>

                        <div className="min-w-0 flex-1 pt-0.5">
                          <div className="flex flex-col justify-between gap-1 sm:flex-row sm:items-start">
                            <h3 className="text-xs font-medium text-zinc-200">
                              {activityDescription(activity.action)}
                            </h3>

                            <time className="shrink-0 text-[10px] text-zinc-600">
                              {formatDate(activity.created_at)}
                            </time>
                          </div>

                          <p className="mt-1 text-[10px] text-zinc-500">
                            By{" "}
                            {getPersonName(
                              activity.actor_id ?? activity.actor_user_id,
                              members,
                              user?.id,
                              user?.full_name,
                            )}
                          </p>

                          {noteText && (
                            <div className="mt-3 whitespace-pre-wrap rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-3 text-xs leading-5 text-zinc-300">
                              {noteText}
                            </div>
                          )}

                          {detailRows.length > 0 && (
                            <details className="mt-2">
                              <summary className="cursor-pointer text-[10px] text-zinc-600 hover:text-zinc-400">
                                View change details
                              </summary>

                              <div className="mt-2 space-y-2 rounded-lg bg-black/20 p-3">
                                {detailRows.map((row, index) => (
                                  <div
                                    key={`${row.label}-${index}`}
                                    className="flex items-start justify-between gap-4"
                                  >
                                    <span className="text-[10px] text-zinc-500">
                                      {row.label}
                                    </span>
                                    <span className="break-words text-right text-[10px] text-zinc-300">
                                      {row.value}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </details>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="mt-6 border-t border-white/[0.06] pt-5">
              <form onSubmit={addNote} className="space-y-3">
                <label
                  htmlFor="progress-note"
                  className="flex items-center gap-2 text-xs font-medium text-zinc-300"
                >
                  <MessageSquare size={14} className="text-zinc-500" />
                  Add a progress note
                </label>

                <textarea
                  id="progress-note"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  maxLength={5000}
                  rows={3}
                  placeholder="Record an investigation result, handoff note, or relevant update..."
                  disabled={Boolean(isSaving)}
                  className="w-full resize-y rounded-lg border border-white/[0.08] bg-[#111114] px-3.5 py-3 text-xs leading-6 outline-none placeholder:text-zinc-600 focus:border-indigo-400/50 disabled:opacity-50"
                />

                <div className="flex items-center justify-between gap-3">
                  <p className="text-[10px] text-zinc-600">
                    {note.length}/5000 characters
                  </p>

                  <button
                    type="submit"
                    disabled={
                      Boolean(isSaving) ||
                      !note.trim() ||
                      note.length > 5000
                    }
                    className="inline-flex h-9 items-center gap-2 rounded-lg bg-zinc-100 px-3.5 text-xs font-semibold text-zinc-950 hover:bg-white disabled:opacity-50"
                  >
                    {isSaving === "note" ? (
                      <LoaderCircle size={13} className="animate-spin" />
                    ) : (
                      <MessageSquare size={13} />
                    )}
                    Add note
                  </button>
                </div>
              </form>
            </div>
          </section>
        </div>

        {/* Workflow panels */}
        <div className="space-y-5">
          {/* Ownership */}
          <section className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 sm:p-6">
            <SectionHeading
              icon={Users}
              title="Ownership"
              description="Manage the person responsible for this work."
            />

            <div className="mt-6">
              {item.assignee_id ? (
                <div className="flex items-start gap-3 rounded-lg border border-white/[0.06] bg-white/[0.015] p-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-indigo-400/10 bg-indigo-400/[0.06]">
                    <UserRound size={16} className="text-indigo-300" />
                  </div>

                  <div className="min-w-0">
                    <p className="text-xs font-medium text-zinc-200">
                      {getPersonName(
                        item.assignee_id,
                        members,
                        user?.id,
                        user?.full_name,
                      )}
                    </p>

                    <p className="mt-1 break-all text-[10px] text-zinc-500">
                      {members.find(
                        (member) => member.user_id === item.assignee_id,
                      )?.email ?? ""}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-white/[0.1] px-3 py-4 text-center">
                  <UserRound size={20} className="mx-auto text-zinc-500" />
                  <p className="mt-2 text-xs text-zinc-300">
                    Unassigned
                  </p>
                  <p className="mt-1 text-[10px] text-zinc-600">
                    No one currently owns this work item.
                  </p>
                </div>
              )}

              <div className="mt-5 space-y-3">
                <div className="space-y-2">
                  <label className="block text-xs font-medium text-zinc-400">
                    Assign to team member
                  </label>

                  <div className="relative">
                    <select
                      value={selectedAssignee}
                      onChange={(event) =>
                        setSelectedAssignee(event.target.value)
                      }
                      disabled={Boolean(isSaving) || members.length === 0}
                      className="h-10 w-full appearance-none rounded-lg border border-white/[0.08] bg-[#121216] px-3 pr-9 text-xs text-zinc-200 outline-none focus:border-indigo-400/50 disabled:opacity-50"
                    >
                      <option value="">Unassigned</option>

                      {members.map((member) => (
                        <option
                          key={member.user_id}
                          value={member.user_id}
                        >
                          {member.full_name}
                        </option>
                      ))}
                    </select>

                    <ChevronDown
                      size={14}
                      className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500"
                    />
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => void saveAssignment()}
                  disabled={
                    Boolean(isSaving) ||
                    !changedAssignee ||
                    (Boolean(selectedAssignee) &&
                      !members.some(
                        (member) => member.user_id === selectedAssignee,
                      ))
                  }
                  className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-white/[0.08] text-xs font-medium text-zinc-200 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {isSaving === "assign" ? (
                    <LoaderCircle size={14} className="animate-spin" />
                  ) : (
                    <Save size={14} />
                  )}
                  Save assignment
                </button>
              </div>
            </div>
          </section>

          {/* Workflow */}
          <section className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 sm:p-6">
            <SectionHeading
              icon={CheckCircle2}
              title="Workflow"
              description="Request a permitted state transition."
            />

            <div className="mt-6 space-y-4">
              <div>
                <p className="mb-2 text-[10px] uppercase tracking-wider text-zinc-600">
                  Current status
                </p>

                <span
                  className={`inline-flex rounded-md border px-2.5 py-1.5 text-xs font-medium ${statusClasses(item.status)}`}
                >
                  {label(item.status)}
                </span>
              </div>

              {allowedNextStatuses.length > 0 ? (
                <>
                  <SelectField
                    labelText="Move to"
                    value={selectedStatus}
                    onChange={(value) =>
                      setSelectedStatus(value as WorkStatus)
                    }
                    options={[item.status, ...allowedNextStatuses]}
                    disabled={Boolean(isSaving)}
                  />

                  <button
                    type="button"
                    onClick={() => void saveStatus()}
                    disabled={Boolean(isSaving) || !changedStatus}
                    className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-white/[0.08] text-xs font-medium text-zinc-200 hover:bg-white/[0.04] disabled:opacity-40"
                  >
                    {isSaving === "status" ? (
                      <LoaderCircle size={14} className="animate-spin" />
                    ) : (
                      <ArrowRight size={14} />
                    )}
                    Apply status
                  </button>
                </>
              ) : (
                <p className="rounded-lg border border-white/[0.06] bg-white/[0.015] p-3 text-xs leading-5 text-zinc-500">
                  No further status transitions are available for this item.
                </p>
              )}

              {item.status === "pending_approval" && (
                <p className="text-[10px] leading-5 text-amber-200/70">
                  This item is awaiting an approval decision. Reviewers must
                  decide through the approval workflow.
                </p>
              )}
            </div>
          </section>

          {/* Priority */}
          <section className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 sm:p-6">
            <SectionHeading
              icon={AlertCircle}
              title="Priority"
              description="Change the item's operational importance."
            />

            <div className="mt-6 space-y-4">
              <SelectField
                labelText="Priority level"
                value={selectedPriority}
                onChange={(value) =>
                  setSelectedPriority(value as WorkPriority)
                }
                options={PRIORITIES}
                disabled={Boolean(isSaving)}
              />

              <button
                type="button"
                onClick={() => void savePriority()}
                disabled={Boolean(isSaving) || !changedPriority}
                className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-white/[0.08] text-xs font-medium text-zinc-200 hover:bg-white/[0.04] disabled:opacity-40"
              >
                {isSaving === "priority" ? (
                  <LoaderCircle size={14} className="animate-spin" />
                ) : (
                  <Save size={14} />
                )}
                Save priority
              </button>
            </div>
          </section>

          {/* Approval history */}
          <section className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 sm:p-6">
            <SectionHeading
              icon={ShieldCheck}
              title="Approvals"
              description="Approval requests associated with this work item."
            />

            <div className="mt-5 space-y-3">
              {approvals.length === 0 ? (
                <p className="rounded-lg border border-white/[0.06] bg-white/[0.015] p-4 text-xs leading-5 text-zinc-500">
                  No approval requests found.
                </p>
              ) : (
                approvals.map((approval) => {
                  const candidates = getApproversForRequest(approval);

                  const selectedForAssignment =
                    assignmentSelections[approval.id] ??
                    getPreferredApprover(candidates)?.user_id ??
                    "";

                  return (
                    <div
                      key={approval.id}
                      className="rounded-lg border border-white/[0.06] bg-white/[0.015] p-3.5"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-xs font-medium text-zinc-300">
                          Approval request
                        </span>

                        <span
                          className={`rounded-md border px-2 py-1 text-[10px] ${statusClasses(approval.status)}`}
                        >
                          {label(approval.status)}
                        </span>
                      </div>

                      <p className="mt-2 text-[10px] text-zinc-500">
                        Requested {formatDate(approval.requested_at)}
                      </p>

                      <p className="mt-2 text-xs text-zinc-400">
                        Requested by{" "}
                        {approval.requester_name ??
                          getPersonName(
                            approval.requested_by,
                            members,
                            user?.id,
                            user?.full_name,
                          )}
                      </p>

                      <p className="mt-2 text-xs text-zinc-400">
                        Approver:{" "}
                        {approval.approver_name ??
                          getPersonName(
                            approval.approver_id,
                            members,
                            user?.id,
                            user?.full_name,
                          )}
                      </p>

                      {approval.decision_reason && (
                        <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-zinc-400">
                          {approval.decision_reason}
                        </p>
                      )}

                      {approval.status === "pending" &&
                        !approval.approver_id && (
                          <div className="mt-4 space-y-3 border-t border-white/[0.06] pt-4">
                            <p className="text-xs leading-5 text-amber-200/80">
                              This request has no assigned approver, so it
                              will not appear in an individual's pending
                              approval queue yet.
                            </p>

                            {candidates.length > 0 ? (
                              <>
                                <MemberSelectField
                                  id={`existing-approver-${approval.id}`}
                                  members={candidates}
                                  value={selectedForAssignment}
                                  onChange={(value) =>
                                    setAssignmentSelections((current) => ({
                                      ...current,
                                      [approval.id]: value,
                                    }))
                                  }
                                  disabled={Boolean(isSaving)}
                                />

                                <button
                                  type="button"
                                  onClick={() =>
                                    void assignExistingApproval(approval)
                                  }
                                  disabled={
                                    Boolean(isSaving) ||
                                    !selectedForAssignment
                                  }
                                  className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-indigo-400/20 bg-indigo-400/[0.05] text-xs font-medium text-indigo-200 transition hover:bg-indigo-400/[0.1] disabled:opacity-40"
                                >
                                  {isSaving === "approval" ? (
                                    <LoaderCircle
                                      size={14}
                                      className="animate-spin"
                                    />
                                  ) : (
                                    <UserRound size={14} />
                                  )}
                                  Assign approver
                                </button>
                              </>
                            ) : (
                              <p className="text-xs leading-5 text-zinc-500">
                                No eligible teammate is available other than
                                the requester. Add another active team lead
                                or designate an approver.
                              </p>
                            )}
                          </div>
                        )}
                    </div>
                  );
                })
              )}

              <Link
                href="/approvals"
                className="flex items-center justify-center gap-2 rounded-lg border border-white/[0.07] px-3 py-2.5 text-xs text-zinc-400 transition hover:bg-white/[0.035] hover:text-white"
              >
                View approvals
                <ArrowRight size={13} />
              </Link>
            </div>
          </section>

          {/* Record information */}
          <section className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 sm:p-6">
            <SectionHeading
              icon={Clock3}
              title="Record information"
              description="Work item lifecycle information."
            />

            <div className="mt-5 space-y-3">
              <div className="flex justify-between gap-4">
                <span className="text-xs text-zinc-500">Team</span>
                <span className="text-right text-xs text-zinc-300">
                  {teamName}
                </span>
              </div>

              <div className="flex justify-between gap-4">
                <span className="text-xs text-zinc-500">Created</span>
                <span className="text-right text-xs text-zinc-300">
                  {formatDate(item.created_at)}
                </span>
              </div>

              <div className="flex justify-between gap-4">
                <span className="text-xs text-zinc-500">Last updated</span>
                <span className="text-right text-xs text-zinc-300">
                  {formatDate(item.updated_at)}
                </span>
              </div>

              {item.completed_at && (
                <div className="flex justify-between gap-4">
                  <span className="text-xs text-zinc-500">Completed</span>
                  <span className="text-right text-xs text-zinc-300">
                    {formatDate(item.completed_at)}
                  </span>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>

      {/* Request approval dialog */}
      {approvalDialogOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-end justify-center bg-black/75 p-0 backdrop-blur-sm sm:items-center sm:p-5"
          onMouseDown={(event) => {
            if (
              event.target === event.currentTarget &&
              !isSaving
            ) {
              setApprovalDialogOpen(false);
            }
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="request-approval-title"
            className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-2xl border border-white/[0.09] bg-[#111114] p-5 shadow-2xl shadow-black/50 sm:rounded-2xl sm:p-7"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.17em] text-zinc-500">
                  Approval workflow
                </p>

                <h2
                  id="request-approval-title"
                  className="mt-2 text-xl font-semibold text-zinc-100"
                >
                  Request approval
                </h2>

                <p className="mt-2 text-sm leading-6 text-zinc-400">
                  Select who should review{" "}
                  <span className="font-medium text-zinc-200">
                    {item.title}
                  </span>
                  .
                </p>
              </div>

              <button
                type="button"
                onClick={() => setApprovalDialogOpen(false)}
                disabled={Boolean(isSaving)}
                aria-label="Close dialog"
                className="rounded-lg p-2 text-zinc-500 transition hover:bg-white/[0.05] hover:text-white disabled:opacity-50"
              >
                <X size={18} />
              </button>
            </div>

            <div className="mt-5 rounded-lg border border-indigo-400/15 bg-indigo-400/[0.04] p-3 text-xs leading-5 text-indigo-100/80">
              The team lead is selected by default. You can choose another
              active team lead or designated approver. Requesters cannot
              approve their own requests.
            </div>

            <form
              onSubmit={submitApprovalRequest}
              className="mt-5 space-y-4"
            >
              {eligibleApprovers.length > 0 ? (
                <>
                  <MemberSelectField
                    id="new-approval-approver"
                    members={eligibleApprovers}
                    value={selectedApproverId}
                    onChange={setSelectedApproverId}
                    disabled={Boolean(isSaving)}
                  />

                  {defaultApprover && (
                    <p className="text-[11px] leading-5 text-zinc-500">
                      Default reviewer:{" "}
                      <span className="text-zinc-300">
                        {defaultApprover.full_name}
                      </span>
                      {" · "}
                      {defaultApprover.role === "lead"
                        ? "Team lead"
                        : "Designated approver"}
                    </p>
                  )}
                </>
              ) : (
                <div className="rounded-lg border border-amber-400/20 bg-amber-400/[0.04] p-4">
                  <p className="text-sm font-medium text-amber-200">
                    No eligible approver is available
                  </p>

                  <p className="mt-2 text-xs leading-5 text-zinc-400">
                    This team needs another active team lead or a member
                    with the approver role. You cannot be assigned to approve
                    your own request.
                  </p>

                  <Link
                    href="/teams"
                    onClick={() => setApprovalDialogOpen(false)}
                    className="mt-3 inline-flex items-center gap-2 text-xs text-zinc-200 underline decoration-white/20 underline-offset-4"
                  >
                    Manage teams
                    <ArrowRight size={13} />
                  </Link>
                </div>
              )}

              {approvalDialogError && (
                <p
                  role="alert"
                  className="rounded-lg border border-red-400/20 bg-red-400/[0.05] p-3 text-xs leading-5 text-red-300"
                >
                  {approvalDialogError}
                </p>
              )}

              <div className="flex flex-col-reverse gap-2 border-t border-white/[0.07] pt-4 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  onClick={() => setApprovalDialogOpen(false)}
                  disabled={Boolean(isSaving)}
                  className="h-10 rounded-lg border border-white/[0.08] px-4 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.04] disabled:opacity-50"
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  disabled={
                    Boolean(isSaving) ||
                    eligibleApprovers.length === 0 ||
                    !selectedApproverId
                  }
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-semibold text-zinc-950 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isSaving === "approval" ? (
                    <>
                      <LoaderCircle size={14} className="animate-spin" />
                      Submitting...
                    </>
                  ) : (
                    <>
                      <ShieldCheck size={14} />
                      Submit for approval
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