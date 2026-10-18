"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  LockKeyhole,
  Mail,
  ShieldCheck,
  UserRound,
} from "lucide-react";

import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/providers/auth-provider";

export default function RegisterPage() {
  const router = useRouter();
  const { register, isLoading, isAuthenticated } = useAuth();

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [registeredEmail, setRegisteredEmail] = useState("");

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [isLoading, isAuthenticated, router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isSubmitting) return;

    setErrorMessage("");

    const normalizedName = fullName.trim();
    const normalizedEmail = email.trim();

    if (!normalizedName || normalizedName.length > 150) {
      setErrorMessage("Your name must contain 1–150 characters.");
      return;
    }

    if (password.length < 12 || password.length > 128) {
      setErrorMessage(
        "Your password must contain between 12 and 128 characters.",
      );
      return;
    }

    if (password !== confirmPassword) {
      setErrorMessage("Your passwords do not match.");
      return;
    }

    setIsSubmitting(true);

    try {
      await register({
        full_name: normalizedName,
        email: normalizedEmail,
        password,
      });

      // Registration creates the account but does not log the
      // user in. Authentication happens through the login flow.
      setRegisteredEmail(normalizedEmail);
      setPassword("");
      setConfirmPassword("");
    } catch (error) {
      if (error instanceof ApiError) {
        if (
          error.status === 409 ||
          error.code === "EMAIL_ALREADY_REGISTERED"
        ) {
          setErrorMessage(
            "An account with this email already exists. Try signing in instead.",
          );
        } else if (error.status === 0) {
          setErrorMessage(
            "Unable to connect to OpsPilot. Check that the backend is running.",
          );
        } else {
          setErrorMessage(error.message);
        }
      } else {
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "We couldn't create your account. Please try again.",
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading || isAuthenticated) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#09090b] text-zinc-100">
        <div className="flex flex-col items-center gap-4" role="status">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-700 border-t-white" />
          <p className="text-sm text-zinc-400">
            {isLoading ? "Restoring your session..." : "Opening workspace..."}
          </p>
        </div>
      </main>
    );
  }

  if (registeredEmail) {
    return (
      <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#09090b] px-5 py-12 text-zinc-100">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -left-40 -top-40 h-[480px] w-[480px] rounded-full bg-indigo-500/[0.08] blur-[140px]"
        />

        <section className="relative w-full max-w-md rounded-2xl border border-white/[0.08] bg-white/[0.025] p-7 shadow-2xl shadow-black/20 sm:p-9">
          <div className="mb-7 flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-400/20 bg-emerald-400/[0.08]">
            <CheckCircle2
              className="h-6 w-6 text-emerald-400"
              aria-hidden="true"
            />
          </div>

          <p className="mb-3 text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Registration complete
          </p>

          <h1 className="text-2xl font-semibold tracking-tight">
            Your account is ready.
          </h1>

          <p className="mt-3 text-sm leading-6 text-zinc-400">
            Your OpsPilot account has been created for{" "}
            <span className="break-all font-medium text-zinc-200">
              {registeredEmail}
            </span>
            . Sign in to access your workspace.
          </p>

          <Link
            href="/login"
            className="mt-8 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-zinc-100 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-white"
          >
            Continue to sign in
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>

          <p className="mt-5 text-center text-xs leading-5 text-zinc-500">
            Registration does not automatically sign you in.
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className="relative flex min-h-screen overflow-hidden bg-[#09090b] text-zinc-100">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 overflow-hidden"
      >
        <div className="absolute -left-40 -top-40 h-[480px] w-[480px] rounded-full bg-indigo-500/[0.08] blur-[140px]" />
        <div className="absolute -bottom-48 -right-40 h-[520px] w-[520px] rounded-full bg-blue-500/[0.07] blur-[150px]" />
      </div>

      {/* Brand panel */}
      <section className="relative hidden w-1/2 flex-col justify-between border-r border-white/[0.07] p-12 lg:flex xl:p-16">
        <Link href="/login" className="flex w-fit items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] text-lg font-bold">
            O
          </div>
          <div>
            <p className="text-sm font-semibold tracking-wide">OpsPilot</p>
            <p className="mt-0.5 text-[11px] text-zinc-500">
              Operations workspace
            </p>
          </div>
        </Link>

        <div className="max-w-lg">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-white/[0.09] bg-white/[0.035] px-3 py-1.5 text-xs text-zinc-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Built for operational clarity
          </div>

          <h1 className="text-4xl font-semibold leading-[1.15] tracking-tight xl:text-5xl">
            Better coordination.
            <br />
            <span className="text-zinc-500">Clear accountability.</span>
            <br />
            One workspace.
          </h1>

          <p className="mt-6 max-w-md text-sm leading-7 text-zinc-400 xl:text-base">
            Bring teams, operational requests, approvals, and important
            decisions into a single, accountable workflow.
          </p>

          <div className="mt-10 space-y-4">
            {[
              {
                title: "Organize operational work",
                description:
                  "Keep priorities, ownership, and progress visible.",
              },
              {
                title: "Work across teams",
                description:
                  "Coordinate responsibilities with controlled access.",
              },
              {
                title: "Preserve important history",
                description:
                  "Make decisions and changes easier to understand.",
              },
            ].map((item) => (
              <div key={item.title} className="flex gap-3">
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.035]">
                  <ShieldCheck
                    className="h-3.5 w-3.5 text-zinc-400"
                    aria-hidden="true"
                  />
                </div>
                <div>
                  <p className="text-sm font-medium text-zinc-200">
                    {item.title}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-zinc-500">
                    {item.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="text-xs text-zinc-600">
          OpsPilot · Operational work management
        </p>
      </section>

      {/* Registration form */}
      <section className="relative flex min-h-screen w-full items-center justify-center px-5 py-10 sm:px-8 lg:w-1/2">
        <div className="w-full max-w-[410px]">
          <Link
            href="/login"
            className="mb-9 flex w-fit items-center gap-3 lg:hidden"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] font-bold">
              O
            </div>
            <div>
              <p className="text-sm font-semibold">OpsPilot</p>
              <p className="text-[11px] text-zinc-500">
                Operations workspace
              </p>
            </div>
          </Link>

          <div className="mb-7">
            <p className="mb-3 text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">
              Get started
            </p>

            <h2 className="text-3xl font-semibold tracking-tight">
              Create your account
            </h2>

            <p className="mt-3 text-sm leading-6 text-zinc-400">
              Set up your account to start coordinating operational work.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="full_name"
                className="mb-2 block text-sm font-medium text-zinc-300"
              >
                Full name
              </label>

              <div className="relative">
                <UserRound
                  className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500"
                  aria-hidden="true"
                />

                <input
                  id="full_name"
                  name="full_name"
                  type="text"
                  autoComplete="name"
                  required
                  minLength={1}
                  maxLength={150}
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  placeholder="Your full name"
                  disabled={isSubmitting}
                  className="h-11 w-full rounded-xl border border-white/[0.09] bg-white/[0.035] pl-11 pr-4 text-sm outline-none transition placeholder:text-zinc-600 hover:border-white/[0.15] focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-400/10 disabled:opacity-60"
                />
              </div>
            </div>

            <div>
              <label
                htmlFor="email"
                className="mb-2 block text-sm font-medium text-zinc-300"
              >
                Email address
              </label>

              <div className="relative">
                <Mail
                  className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500"
                  aria-hidden="true"
                />

                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  autoCapitalize="none"
                  spellCheck={false}
                  required
                  maxLength={254}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@company.com"
                  disabled={isSubmitting}
                  className="h-11 w-full rounded-xl border border-white/[0.09] bg-white/[0.035] pl-11 pr-4 text-sm outline-none transition placeholder:text-zinc-600 hover:border-white/[0.15] focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-400/10 disabled:opacity-60"
                />
              </div>
            </div>

            <div>
              <label
                htmlFor="password"
                className="mb-2 block text-sm font-medium text-zinc-300"
              >
                Password
              </label>

              <div className="relative">
                <LockKeyhole
                  className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500"
                  aria-hidden="true"
                />

                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  required
                  minLength={12}
                  maxLength={128}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="At least 12 characters"
                  disabled={isSubmitting}
                  className="h-11 w-full rounded-xl border border-white/[0.09] bg-white/[0.035] pl-11 pr-12 text-sm outline-none transition placeholder:text-zinc-600 hover:border-white/[0.15] focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-400/10 disabled:opacity-60"
                />

                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-zinc-500 transition hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Eye className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </div>

              <p className="mt-2 text-xs text-zinc-500">
                Use between 12 and 128 characters.
              </p>
            </div>

            <div>
              <label
                htmlFor="confirm_password"
                className="mb-2 block text-sm font-medium text-zinc-300"
              >
                Confirm password
              </label>

              <div className="relative">
                <LockKeyhole
                  className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500"
                  aria-hidden="true"
                />

                <input
                  id="confirm_password"
                  name="confirm_password"
                  type={showConfirmPassword ? "text" : "password"}
                  autoComplete="new-password"
                  required
                  maxLength={128}
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  placeholder="Enter your password again"
                  disabled={isSubmitting}
                  className="h-11 w-full rounded-xl border border-white/[0.09] bg-white/[0.035] pl-11 pr-12 text-sm outline-none transition placeholder:text-zinc-600 hover:border-white/[0.15] focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-400/10 disabled:opacity-60"
                />

                <button
                  type="button"
                  onClick={() => setShowConfirmPassword((value) => !value)}
                  aria-label={
                    showConfirmPassword
                      ? "Hide confirmation password"
                      : "Show confirmation password"
                  }
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-zinc-500 transition hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                >
                  {showConfirmPassword ? (
                    <EyeOff className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Eye className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </div>
            </div>

            {errorMessage && (
              <div
                role="alert"
                aria-live="polite"
                className="rounded-xl border border-red-400/20 bg-red-500/[0.07] px-4 py-3 text-sm leading-6 text-red-300"
              >
                {errorMessage}
              </div>
            )}

            <button
              type="submit"
              disabled={
                isSubmitting ||
                !fullName.trim() ||
                !email.trim() ||
                !password ||
                !confirmPassword
              }
              className="group mt-2 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-zinc-100 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#09090b] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-400 border-t-zinc-950" />
                  Creating account...
                </>
              ) : (
                <>
                  Create account
                  <ArrowRight
                    className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                    aria-hidden="true"
                  />
                </>
              )}
            </button>
          </form>

          <div className="my-6 border-t border-white/[0.07]" />

          <p className="text-center text-sm text-zinc-400">
            Already have an account?{" "}
            <Link
              href="/login"
              className="font-medium text-zinc-100 underline decoration-white/25 underline-offset-4 transition hover:decoration-white"
            >
              Sign in
            </Link>
          </p>

          <div className="mt-8 flex items-center justify-center gap-2 text-[11px] text-zinc-600">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
            Your account permissions are enforced by OpsPilot.
          </div>
        </div>
      </section>
    </main>
  );
}