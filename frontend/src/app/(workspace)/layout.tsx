"use client";

import { Suspense, useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/layout/app-shell";
import { useAuth } from "@/providers/auth-provider";

function PageLoadingFallback() {
  return (
    <div
      className="mx-auto max-w-[1600px] space-y-6"
      role="status"
      aria-live="polite"
      aria-label="Loading workspace page"
    >
      <div className="space-y-3">
        <div className="h-3 w-24 animate-pulse rounded bg-white/[0.06]" />
        <div className="h-8 w-56 animate-pulse rounded bg-white/[0.06]" />
        <div className="h-4 w-80 max-w-full animate-pulse rounded bg-white/[0.04]" />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div
            key={index}
            className="h-28 animate-pulse rounded-xl border border-white/[0.07] bg-white/[0.02]"
          />
        ))}
      </div>

      <div className="h-72 animate-pulse rounded-xl border border-white/[0.07] bg-white/[0.02]" />

      <span className="sr-only">Loading page content…</span>
    </div>
  );
}

export default function WorkspaceLayout({
  children,
}: {
  children: ReactNode;
}) {
  const router = useRouter();
  const { isLoading, isAuthenticated } = useAuth();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  return (
    <AppShell>
      <Suspense fallback={<PageLoadingFallback />}>
        {children}
      </Suspense>
    </AppShell>
  );
}