
"use client";

import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  CheckCircle2,
  Eye,
  EyeOff,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  Save,
  ShieldCheck,
  UserRound,
  X,
} from "lucide-react";

import { api, ApiError } from "@/lib/api-client";

interface AccountProfile {
  id: string;
  full_name: string;
  email: string;
  account_status: string;
  created_at: string | null;
  updated_at: string | null;
}

interface ProfileApiResponse {
  user?: Partial<AccountProfile> | null;
  id?: string;
  full_name?: string;
  email?: string;
  account_status?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

interface ProfileUpdateResponse {
  user?: Partial<AccountProfile> | null;
  id?: string;
  full_name?: string;
  email?: string;
  account_status?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return "Unable to reach the backend. Check that the API is running.";
    }

    if (error.status === 401) {
      return "Your session has expired. Please sign in again.";
    }

    if (error.status === 403) {
      return "You are not authorized to perform this operation.";
    }

    if (error.status === 409) {
      return error.message || "This change conflicts with the current account state.";
    }

    if (error.status === 422) {
      return error.message || "Please check the information you entered.";
    }

    return error.message || "The request failed. Please try again.";
  }

  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}

function normalizeProfile(
  response: ProfileApiResponse | ProfileUpdateResponse,
): AccountProfile {
  const user = response.user ?? response;

  return {
    id: user.id ?? "",
    full_name: user.full_name ?? "",
    email: user.email ?? "",
    account_status: user.account_status ?? "unknown",
    created_at: user.created_at ?? null,
    updated_at: user.updated_at ?? null,
  };
}

function formatDate(value?: string | null): string {
  if (!value) return "Not available";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "Not available";

  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function getInitials(name?: string | null): string {
  return (
    (name ?? "")
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0] ?? "")
      .join("")
      .toUpperCase() || "U"
  );
}

function statusClasses(status: string): string {
  switch (status.toLowerCase()) {
    case "active":
      return "border-emerald-400/20 bg-emerald-400/[0.07] text-emerald-300";
    case "suspended":
    case "disabled":
    case "inactive":
      return "border-red-400/20 bg-red-400/[0.07] text-red-300";
    default:
      return "border-white/[0.10] bg-white/[0.04] text-zinc-400";
  }
}

function SectionTitle({
  icon,
  title,
  description,
}: {
  icon: ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/[0.07] bg-white/[0.025] text-zinc-300">
        {icon}
      </div>
      <div>
        <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>
        <p className="mt-1 text-xs leading-5 text-zinc-500">
          {description}
        </p>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [profile, setProfile] = useState<AccountProfile | null>(null);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const [isLoading, setIsLoading] = useState(true);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  const [pageError, setPageError] = useState("");
  const [profileError, setProfileError] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [notice, setNotice] = useState("");

  const loadProfile = useCallback(async () => {
    setIsLoading(true);
    setPageError("");

    try {
      const response = await api.get<ProfileApiResponse>("accounts/me");
      const raw = response.outputs.data;

      if (!raw) {
        setPageError("The profile response did not contain account data.");
        return;
      }

      const data = normalizeProfile(raw);

      setProfile(data);
      setFullName(data.full_name);
      setEmail(data.email);
    } catch (error) {
      setPageError(getErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function initializeProfile() {
      try {
        const response = await api.get<ProfileApiResponse>("accounts/me");

        if (cancelled) return;

        const raw = response.outputs.data;

        if (!raw) {
          setPageError("The profile response did not contain account data.");
          return;
        }

        const data = normalizeProfile(raw);

        setProfile(data);
        setFullName(data.full_name);
        setEmail(data.email);
        setPageError("");
      } catch (error) {
        if (!cancelled) {
          setPageError(getErrorMessage(error));
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void initializeProfile();

    return () => {
      cancelled = true;
    };
  }, []);

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isSavingProfile) return;

    const cleanedName = fullName.trim();
    const cleanedEmail = email.trim();

    if (!cleanedName) {
      setProfileError("Full name is required.");
      return;
    }

    if (cleanedName.length > 150) {
      setProfileError("Full name must not exceed 150 characters.");
      return;
    }

    if (
      !cleanedEmail ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanedEmail)
    ) {
      setProfileError("Enter a valid email address.");
      return;
    }

    setIsSavingProfile(true);
    setProfileError("");
    setNotice("");

    try {
      const response = await api.patch<ProfileUpdateResponse>(
        "accounts/me",
        {
          full_name: cleanedName,
          email: cleanedEmail,
        },
      );

      const updated = response.outputs.data;
      const normalized = updated ? normalizeProfile(updated) : null;

      setProfile((current) =>
        current
          ? {
              ...current,
              ...(normalized ?? {}),
              full_name: normalized?.full_name || cleanedName,
              email: normalized?.email || cleanedEmail,
            }
          : current,
      );

      setFullName(normalized?.full_name || cleanedName);
      setEmail(normalized?.email || cleanedEmail);
      setNotice("Your profile has been updated successfully.");
    } catch (error) {
      setProfileError(getErrorMessage(error));
    } finally {
      setIsSavingProfile(false);
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isChangingPassword) return;

    if (!currentPassword) {
      setPasswordError("Enter your current password.");
      return;
    }

    if (newPassword.length < 8) {
      setPasswordError("Your new password must contain at least 8 characters.");
      return;
    }

    if (newPassword.length > 128) {
      setPasswordError("Your new password must not exceed 128 characters.");
      return;
    }

    if (newPassword === currentPassword) {
      setPasswordError(
        "Your new password must differ from your current password.",
      );
      return;
    }

    if (newPassword !== confirmPassword) {
      setPasswordError("The new password and confirmation do not match.");
      return;
    }

    setIsChangingPassword(true);
    setPasswordError("");
    setNotice("");

    try {
      await api.patch("accounts/me/password", {
        current_password: currentPassword,
        new_password: newPassword,
      });

      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setNotice("Your password has been changed successfully.");
    } catch (error) {
      setPasswordError(getErrorMessage(error));
    } finally {
      setIsChangingPassword(false);
    }
  }

  const inputClass =
    "h-11 w-full rounded-lg border border-white/[0.09] bg-black/20 px-3.5 text-sm text-zinc-200 outline-none transition placeholder:text-zinc-600 focus:border-indigo-400/50 disabled:cursor-not-allowed disabled:opacity-50";

  const passwordInputClass =
    "h-11 w-full rounded-lg border border-white/[0.09] bg-black/20 px-3.5 pr-11 text-sm text-zinc-200 outline-none transition placeholder:text-zinc-600 focus:border-indigo-400/50 disabled:cursor-not-allowed disabled:opacity-50";

  const accountStatus = profile?.account_status ?? "unknown";

  return (
    <div className="mx-auto max-w-[1100px] space-y-7">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 flex items-center gap-2 text-xs text-zinc-500">
            <span>Workspace</span>
            <span className="text-zinc-700">/</span>
            <span className="text-zinc-300">Settings</span>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight text-zinc-100 sm:text-3xl">
            Account settings
          </h1>

          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
            Manage your profile information and account security.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void loadProfile()}
          disabled={isLoading || isSavingProfile || isChangingPassword}
          className="inline-flex h-10 items-center justify-center gap-2 self-start rounded-lg border border-white/[0.08] px-4 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.04] disabled:opacity-50 sm:self-auto"
        >
          <RefreshCw
            size={14}
            className={isLoading ? "animate-spin" : ""}
          />
          Refresh
        </button>
      </header>

      {notice && (
        <div
          role="status"
          className="flex items-center gap-3 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.05] px-4 py-3 text-sm text-emerald-200"
        >
          <CheckCircle2 size={17} className="shrink-0" />
          <p className="flex-1">{notice}</p>
          <button
            type="button"
            aria-label="Dismiss notification"
            onClick={() => setNotice("")}
          >
            <X size={15} />
          </button>
        </div>
      )}

      {pageError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-xl border border-red-400/20 bg-red-400/[0.04] p-4"
        >
          <AlertCircle size={17} className="mt-0.5 shrink-0 text-red-300" />
          <div className="flex-1">
            <p className="text-sm leading-6 text-red-200">{pageError}</p>
            <button
              type="button"
              onClick={() => void loadProfile()}
              className="mt-2 text-xs text-zinc-300 underline underline-offset-4"
            >
              Try again
            </button>
          </div>
        </div>
      )}

      {isLoading && !profile ? (
        <div className="space-y-5">
          <div className="h-36 animate-pulse rounded-xl border border-white/[0.06] bg-white/[0.02]" />
          <div className="h-72 animate-pulse rounded-xl border border-white/[0.06] bg-white/[0.02]" />
          <div className="h-72 animate-pulse rounded-xl border border-white/[0.06] bg-white/[0.02]" />
        </div>
      ) : profile ? (
        <>
          <section className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 sm:p-6">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border border-indigo-400/20 bg-indigo-400/[0.08] text-lg font-semibold text-indigo-200">
                {getInitials(profile.full_name)}
              </div>

              <div className="min-w-0 flex-1">
                <h2 className="break-words text-lg font-semibold text-zinc-100">
                  {profile.full_name || "Name not provided"}
                </h2>
                <p className="mt-1 break-all text-sm text-zinc-400">
                  {profile.email || "Email not provided"}
                </p>
                <div className="mt-3">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-medium ${statusClasses(accountStatus)}`}
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-current" />
                    {accountStatus.replaceAll("_", " ")}
                  </span>
                </div>
              </div>

              <div className="rounded-lg border border-white/[0.06] bg-black/10 px-4 py-3 sm:min-w-44">
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">
                  Account created
                </p>
                <p className="mt-2 text-xs font-medium text-zinc-300">
                  {formatDate(profile.created_at)}
                </p>
              </div>
            </div>
          </section>

          <section className="rounded-xl border border-white/[0.07] bg-white/[0.015]">
            <div className="border-b border-white/[0.07] p-5 sm:p-6">
              <SectionTitle
                icon={<UserRound size={18} />}
                title="Personal information"
                description="Update the name and email address associated with your account."
              />
            </div>

            <form onSubmit={saveProfile} className="space-y-5 p-5 sm:p-6">
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                <div className="space-y-2">
                  <label
                    htmlFor="settings-full-name"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Full name
                  </label>
                  <input
                    id="settings-full-name"
                    autoComplete="name"
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                    maxLength={150}
                    required
                    disabled={isSavingProfile}
                    placeholder="Your full name"
                    className={inputClass}
                  />
                </div>

                <div className="space-y-2">
                  <label
                    htmlFor="settings-email"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Email address
                  </label>
                  <input
                    id="settings-email"
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    maxLength={254}
                    required
                    disabled={isSavingProfile}
                    placeholder="you@example.com"
                    className={inputClass}
                  />
                </div>
              </div>

              <div className="flex flex-col gap-3 border-t border-white/[0.06] pt-5 sm:flex-row sm:items-center sm:justify-between">
                {profileError ? (
                  <p role="alert" className="text-xs leading-5 text-red-300">
                    {profileError}
                  </p>
                ) : (
                  <p className="text-xs leading-5 text-zinc-600">
                    Your changes are saved to your account.
                  </p>
                )}

                <button
                  type="submit"
                  disabled={
                    isSavingProfile ||
                    !fullName.trim() ||
                    !email.trim()
                  }
                  className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-semibold text-zinc-950 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isSavingProfile ? (
                    <LoaderCircle size={14} className="animate-spin" />
                  ) : (
                    <Save size={14} />
                  )}
                  Save changes
                </button>
              </div>
            </form>
          </section>

          <section className="rounded-xl border border-white/[0.07] bg-white/[0.015]">
            <div className="border-b border-white/[0.07] p-5 sm:p-6">
              <SectionTitle
                icon={<LockKeyhole size={18} />}
                title="Password and security"
                description="Change your password to help keep your account secure."
              />
            </div>

            <form
              onSubmit={changePassword}
              className="space-y-5 p-5 sm:p-6"
            >
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                <div className="space-y-2 sm:col-span-2">
                  <label
                    htmlFor="current-password"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Current password
                  </label>

                  <div className="relative">
                    <input
                      id="current-password"
                      type={showCurrentPassword ? "text" : "password"}
                      autoComplete="current-password"
                      value={currentPassword}
                      onChange={(event) =>
                        setCurrentPassword(event.target.value)
                      }
                      required
                      disabled={isChangingPassword}
                      className={passwordInputClass}
                      placeholder="Enter your current password"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setShowCurrentPassword((value) => !value)
                      }
                      aria-label={
                        showCurrentPassword
                          ? "Hide current password"
                          : "Show current password"
                      }
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                    >
                      {showCurrentPassword ? (
                        <EyeOff size={16} />
                      ) : (
                        <Eye size={16} />
                      )}
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <label
                    htmlFor="new-password"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    New password
                  </label>

                  <div className="relative">
                    <input
                      id="new-password"
                      type={showNewPassword ? "text" : "password"}
                      autoComplete="new-password"
                      value={newPassword}
                      onChange={(event) => setNewPassword(event.target.value)}
                      minLength={8}
                      maxLength={128}
                      required
                      disabled={isChangingPassword}
                      className={passwordInputClass}
                      placeholder="At least 8 characters"
                    />
                    <button
                      type="button"
                      onClick={() => setShowNewPassword((value) => !value)}
                      aria-label={
                        showNewPassword ? "Hide new password" : "Show new password"
                      }
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                    >
                      {showNewPassword ? (
                        <EyeOff size={16} />
                      ) : (
                        <Eye size={16} />
                      )}
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <label
                    htmlFor="confirm-password"
                    className="block text-xs font-medium text-zinc-300"
                  >
                    Confirm new password
                  </label>

                  <div className="relative">
                    <input
                      id="confirm-password"
                      type={showConfirmPassword ? "text" : "password"}
                      autoComplete="new-password"
                      value={confirmPassword}
                      onChange={(event) =>
                        setConfirmPassword(event.target.value)
                      }
                      minLength={8}
                      maxLength={128}
                      required
                      disabled={isChangingPassword}
                      className={passwordInputClass}
                      placeholder="Re-enter new password"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setShowConfirmPassword((value) => !value)
                      }
                      aria-label={
                        showConfirmPassword
                          ? "Hide confirmation password"
                          : "Show confirmation password"
                      }
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                    >
                      {showConfirmPassword ? (
                        <EyeOff size={16} />
                      ) : (
                        <Eye size={16} />
                      )}
                    </button>
                  </div>
                </div>
              </div>

              <div className="rounded-lg border border-white/[0.06] bg-black/10 p-3">
                <div className="flex items-start gap-2.5">
                  <ShieldCheck
                    size={15}
                    className="mt-0.5 shrink-0 text-zinc-400"
                  />
                  <p className="text-xs leading-5 text-zinc-500">
                    Use a unique password that you do not use for other
                    accounts. Your current password is required to make this
                    change.
                  </p>
                </div>
              </div>

              {passwordError && (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-lg border border-red-400/20 bg-red-400/[0.04] p-3 text-xs leading-5 text-red-300"
                >
                  <AlertCircle
                    size={15}
                    className="mt-0.5 shrink-0"
                  />
                  <p>{passwordError}</p>
                </div>
              )}

              <div className="flex flex-col gap-3 border-t border-white/[0.06] pt-5 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs leading-5 text-zinc-600">
                  Password updates are processed securely by the backend.
                </p>

                <button
                  type="submit"
                  disabled={
                    isChangingPassword ||
                    !currentPassword ||
                    !newPassword ||
                    !confirmPassword
                  }
                  className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg border border-white/[0.09] bg-white/[0.04] px-4 text-xs font-medium text-zinc-200 transition hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isChangingPassword ? (
                    <LoaderCircle size={14} className="animate-spin" />
                  ) : (
                    <LockKeyhole size={14} />
                  )}
                  Update password
                </button>
              </div>
            </form>
          </section>

          <section className="rounded-xl border border-white/[0.07] bg-white/[0.015] p-5 sm:p-6">
            <h2 className="text-sm font-semibold text-zinc-100">
              Account information
            </h2>

            <p className="mt-1 text-xs leading-5 text-zinc-500">
              System-managed details about your account.
            </p>

            <div className="mt-5 divide-y divide-white/[0.06]">
              <div className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-xs text-zinc-500">Account status</span>
                <span
                  className={`w-fit rounded-md border px-2 py-1 text-[10px] font-medium ${statusClasses(accountStatus)}`}
                >
                  {accountStatus.replaceAll("_", " ")}
                </span>
              </div>

              <div className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-xs text-zinc-500">
                  Last profile update
                </span>
                <span className="text-xs text-zinc-300">
                  {formatDate(profile.updated_at)}
                </span>
              </div>

              <div className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-xs text-zinc-500">Account created</span>
                <span className="text-xs text-zinc-300">
                  {formatDate(profile.created_at)}
                </span>
              </div>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
