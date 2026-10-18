"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Eye,
  EyeOff,
  LockKeyhole,
  Mail,
  ShieldCheck,
} from "lucide-react";

import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/providers/auth-provider";

export default function LoginPage() {
  const router = useRouter();
  const { login, isLoading, isAuthenticated } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [isLoading, isAuthenticated, router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isSubmitting) return;

    setErrorMessage("");
    setIsSubmitting(true);

    try {
      await login({
        email: email.trim(),
        password,
      });

      router.replace("/dashboard");
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 401) {
          setErrorMessage(
            "The email or password is incorrect. Please try again.",
          );
        } else if (error.status === 403) {
          setErrorMessage(
            "Your account cannot access OpsPilot. Contact your administrator.",
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
            : "Something went wrong. Please try again.",
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

  return (
    <main className="relative flex min-h-screen overflow-hidden bg-[#09090b] text-zinc-100">
      {/* Ambient background */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 overflow-hidden"
      >
        <div className="absolute -left-40 -top-40 h-[480px] w-[480px] rounded-full bg-indigo-500/[0.08] blur-[140px]" />
        <div className="absolute -bottom-48 -right-40 h-[520px] w-[520px] rounded-full bg-blue-500/[0.07] blur-[150px]" />
      </div>

      {/* Brand / challenge context */}
      <section className="relative hidden w-1/2 flex-col justify-between border-r border-white/[0.07] p-12 lg:flex xl:p-16">
        <Link href="/frontend/public" className="flex w-fit items-center gap-3">
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
            Critical work.
            <br />
            <span className="text-zinc-500">Clear ownership.</span>
            <br />
            Fewer surprises.
          </h1>

          <p className="mt-6 max-w-md text-sm leading-7 text-zinc-400 xl:text-base">
            A centralized workspace for managing operational work,
            coordinating teams, resolving approvals, and understanding
            what needs attention next.
          </p>

          <div className="mt-10 space-y-4">
            {[
              {
                title: "One source of truth",
                description:
                  "Work items, ownership, and history in one place.",
              },
              {
                title: "Controlled workflows",
                description:
                  "Assignments and approvals with explicit rules.",
              },
              {
                title: "Accountable decisions",
                description:
                  "A history of important changes and decisions.",
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

      {/* Login form */}
      <section className="relative flex min-h-screen w-full items-center justify-center px-5 py-12 sm:px-8 lg:w-1/2">
        <div className="w-full max-w-[400px]">
          <Link href="/frontend/public" className="mb-12 flex w-fit items-center gap-3 lg:hidden">
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

          <div className="mb-8">
            <p className="mb-3 text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">
              Welcome back
            </p>

            <h2 className="text-3xl font-semibold tracking-tight">
              Sign in to OpsPilot
            </h2>

            <p className="mt-3 text-sm leading-6 text-zinc-400">
              Enter your account details to access your workspace.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
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
                  className="h-12 w-full rounded-xl border border-white/[0.09] bg-white/[0.035] pl-11 pr-4 text-sm text-zinc-100 outline-none transition placeholder:text-zinc-600 hover:border-white/[0.15] focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-400/10 disabled:opacity-60"
                />
              </div>
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between">
                <label
                  htmlFor="password"
                  className="block text-sm font-medium text-zinc-300"
                >
                  Password
                </label>
              </div>

              <div className="relative">
                <LockKeyhole
                  className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500"
                  aria-hidden="true"
                />

                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  maxLength={128}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Enter your password"
                  disabled={isSubmitting}
                  className="h-12 w-full rounded-xl border border-white/[0.09] bg-white/[0.035] pl-11 pr-12 text-sm text-zinc-100 outline-none transition placeholder:text-zinc-600 hover:border-white/[0.15] focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-400/10 disabled:opacity-60"
                />

                <button
                  type="button"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={
                    showPassword ? "Hide password" : "Show password"
                  }
                  aria-pressed={showPassword}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-zinc-500 transition hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                >
                  {showPassword ? (
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
              disabled={isSubmitting || !email.trim() || !password}
              className="group flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-zinc-100 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#09090b] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-400 border-t-zinc-950" />
                  Signing in...
                </>
              ) : (
                <>
                  Sign in
                  <ArrowRight
                    className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                    aria-hidden="true"
                  />
                </>
              )}
            </button>
          </form>

          <div className="my-7 border-t border-white/[0.07]" />

          <p className="text-center text-sm text-zinc-400">
            New to OpsPilot?{" "}
            <Link
              href="/register"
              className="font-medium text-zinc-100 underline decoration-white/25 underline-offset-4 transition hover:decoration-white"
            >
              Create an account
            </Link>
          </p>

          <div className="mt-10 flex items-center justify-center gap-2 text-[11px] text-zinc-600">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
            Your workspace access is controlled by your account permissions.
          </div>
        </div>
      </section>
    </main>
  );
}