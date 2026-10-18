"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/providers/auth-provider";

export default function HomePage() {
  const router = useRouter();
  const { isLoading, isAuthenticated } = useAuth();

  useEffect(() => {
    if (isLoading) {
      return;
    }

    if (isAuthenticated) {
      router.replace("/dashboard");
    } else {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-950 text-zinc-100">
      <div
        className="flex flex-col items-center gap-5"
        role="status"
        aria-live="polite"
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04]">
          <span className="text-xl font-semibold tracking-tight">
            O
          </span>
        </div>

        <div className="flex flex-col items-center gap-2">
          <p className="text-sm font-medium tracking-wide">
            OpsPilot
          </p>

          <p className="text-xs text-zinc-500">
            {isLoading
              ? "Restoring your session..."
              : "Opening your workspace..."}
          </p>
        </div>

        <div
          className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-700 border-t-zinc-100"
          aria-hidden="true"
        />
      </div>
    </main>
  );
}