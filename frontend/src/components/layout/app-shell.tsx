"use client";

import { Suspense, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  ArrowUpRight,
  Bell,
  ChevronDown,
  ClipboardList,
  LayoutDashboard,
  LogOut,
  Menu,
  Settings,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";

import { useAuth } from "@/providers/auth-provider";

const navigation = [
  { label: "Overview", href: "/dashboard", icon: LayoutDashboard },
  { label: "Work items", href: "/work-items", icon: ClipboardList },
  { label: "Approvals", href: "/approvals", icon: ShieldCheck },
  { label: "Teams", href: "/teams", icon: Users },
  { label: "Activity", href: "/activity", icon: Activity },
];

interface AppShellProps {
  children: ReactNode;
}

function getInitials(name: string): string {
  return (
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part.charAt(0))
      .join("")
      .toUpperCase() || "U"
  );
}

function getPageTitle(pathname: string): string {
  if (pathname === "/dashboard") return "Overview";
  if (pathname.startsWith("/work-items")) return "Work items";
  if (pathname.startsWith("/approvals")) return "Approvals";
  if (pathname.startsWith("/teams")) return "Teams";
  if (pathname.startsWith("/activity")) return "Activity";
  if (pathname.startsWith("/settings")) return "Settings";
  return "Workspace";
}

function SidebarNavigation({
  onNavigate,
}: {
  onNavigate: () => void;
}) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main navigation" className="space-y-1">
      {navigation.map((item) => {
        const Icon = item.icon;

        const active =
          pathname === item.href ||
          (item.href !== "/dashboard" &&
            pathname.startsWith(`${item.href}/`));

        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={[
              "group flex h-10 items-center gap-3 rounded-lg px-3 text-[13px] transition-colors",
              active
                ? "border border-white/[0.08] bg-white/[0.07] font-medium text-white"
                : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-100",
            ].join(" ")}
          >
            <Icon
              size={17}
              strokeWidth={active ? 2 : 1.7}
              className={
                active
                  ? "text-zinc-100"
                  : "text-zinc-500 transition-colors group-hover:text-zinc-300"
              }
            />

            <span>{item.label}</span>

            {active && (
              <span
                className="ml-auto h-1.5 w-1.5 rounded-full bg-indigo-400"
                aria-hidden="true"
              />
            )}
          </Link>
        );
      })}
    </nav>
  );
}

function SidebarNavigationFallback() {
  return (
    <nav aria-label="Main navigation" className="space-y-1">
      {navigation.map((item) => {
        const Icon = item.icon;

        return (
          <div
            key={item.href}
            className="flex h-10 items-center gap-3 rounded-lg px-3 text-[13px] text-zinc-400"
          >
            <Icon size={17} className="text-zinc-500" />
            <span>{item.label}</span>
          </div>
        );
      })}
    </nav>
  );
}

function RouteHeaderInfo() {
  const pathname = usePathname();
  const title = getPageTitle(pathname);

  return (
    <div className="min-w-0">
      <p className="text-sm font-medium text-zinc-100">{title}</p>

      <p className="mt-1 hidden text-[11px] text-zinc-500 sm:block">
        Operations workspace
        <span className="mx-2 text-zinc-700">/</span>
        <span className="text-zinc-400">{title}</span>
      </p>
    </div>
  );
}

function RouteHeaderFallback() {
  return (
    <div className="min-w-0">
      <p className="text-sm font-medium text-zinc-100">Workspace</p>
      <p className="mt-1 hidden text-[11px] text-zinc-500 sm:block">
        Operations workspace
      </p>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-[72px] items-center gap-3 border-b border-white/[0.07] px-6">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] text-sm font-bold text-white">
          O
        </div>

        <div>
          <p className="text-sm font-semibold tracking-wide text-zinc-100">
            OpsPilot
          </p>
          <p className="mt-0.5 text-[10px] uppercase tracking-[0.15em] text-zinc-500">
            Operations platform
          </p>
        </div>
      </div>

      <div className="px-4 pt-7">
        <p className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-600">
          Workspace
        </p>

        <Suspense fallback={<SidebarNavigationFallback />}>
          <SidebarNavigation onNavigate={onNavigate} />
        </Suspense>
      </div>

      <div className="mt-auto px-4 pb-5">
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-indigo-400/10 text-indigo-300">
              <ShieldCheck size={15} />
            </div>

            <div className="min-w-0">
              <p className="text-xs font-medium text-zinc-300">
                Controlled access
              </p>
              <p className="mt-0.5 text-[10px] text-zinc-500">
                Permissions enforced by server
              </p>
            </div>
          </div>
        </div>

        <p className="mt-4 px-2 text-[10px] text-zinc-600">
          OpsPilot · v1.0
        </p>
      </div>
    </div>
  );
}

export function AppShell({ children }: AppShellProps) {
  const router = useRouter();
  const { user, logout } = useAuth();

  const [mobileOpen, setMobileOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");

  const name = user?.full_name || "User";
  const email = user?.email || "";

  async function handleLogout() {
    if (isLoggingOut) return;

    setLogoutError("");
    setIsLoggingOut(true);

    try {
      await logout();
      router.replace("/login");
    } catch {
      setLogoutError("Logout could not be confirmed. Please try again.");
    } finally {
      setIsLoggingOut(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#09090b] text-zinc-100 lg:flex">
      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm lg:hidden"
        />
      )}

      <aside
        className={[
          "fixed inset-y-0 left-0 z-50 w-[260px] border-r border-white/[0.07] bg-[#0d0d10] transition-transform duration-200 lg:static lg:z-auto lg:min-h-screen lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        ].join(" ")}
      >
        <div className="absolute right-3 top-5 z-10 lg:hidden">
          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
            className="rounded-lg p-2 text-zinc-400 hover:bg-white/[0.05] hover:text-white"
          >
            <X size={18} />
          </button>
        </div>

        <Sidebar onNavigate={() => setMobileOpen(false)} />
      </aside>

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-[72px] shrink-0 items-center justify-between border-b border-white/[0.07] bg-[#09090b]/95 px-4 backdrop-blur-xl sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation"
              className="rounded-lg border border-white/[0.08] p-2 text-zinc-400 hover:bg-white/[0.05] hover:text-white lg:hidden"
            >
              <Menu size={18} />
            </button>

            <Suspense fallback={<RouteHeaderFallback />}>
              <RouteHeaderInfo />
            </Suspense>
          </div>

          <div className="flex items-center gap-2 sm:gap-4">
            <div className="hidden items-center gap-2 rounded-full border border-white/[0.07] bg-white/[0.025] px-3 py-1.5 md:flex">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              <span className="text-[11px] text-zinc-400">
                Workspace active
              </span>
            </div>

            <button
              type="button"
              aria-label="Notifications"
              title="Notifications"
              className="hidden rounded-lg border border-white/[0.07] p-2 text-zinc-400 transition hover:bg-white/[0.05] hover:text-white sm:inline-flex"
            >
              <Bell size={17} />
            </button>

            <div className="relative">
              <button
                type="button"
                onClick={() => setUserMenuOpen((open) => !open)}
                aria-expanded={userMenuOpen}
                aria-haspopup="menu"
                className="flex items-center gap-2 rounded-xl border border-white/[0.07] bg-white/[0.025] py-1.5 pl-1.5 pr-2 transition hover:bg-white/[0.05] sm:gap-3 sm:pl-2"
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-indigo-300/10 bg-indigo-400/10 text-xs font-semibold text-indigo-200">
                  {getInitials(name)}
                </div>

                <div className="hidden max-w-[150px] text-left sm:block">
                  <p className="truncate text-xs font-medium text-zinc-200">
                    {name}
                  </p>
                  <p className="mt-0.5 truncate text-[10px] text-zinc-500">
                    {email}
                  </p>
                </div>

                <ChevronDown
                  size={14}
                  className="hidden text-zinc-500 sm:block"
                />
              </button>

              {userMenuOpen && (
                <>
                  <button
                    type="button"
                    aria-label="Close user menu"
                    className="fixed inset-0 z-40 cursor-default"
                    onClick={() => setUserMenuOpen(false)}
                  />

                  <div
                    role="menu"
                    className="absolute right-0 top-full z-50 mt-2 w-64 rounded-xl border border-white/[0.09] bg-[#141418] p-2 shadow-2xl shadow-black/50"
                  >
                    <div className="border-b border-white/[0.07] px-3 py-3">
                      <p className="truncate text-sm font-medium text-zinc-100">
                        {name}
                      </p>
                      <p className="mt-1 truncate text-xs text-zinc-500">
                        {email}
                      </p>
                    </div>

                    <Link
                      href="/settings"
                      role="menuitem"
                      onClick={() => setUserMenuOpen(false)}
                      className="mt-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-zinc-300 hover:bg-white/[0.05] hover:text-white"
                    >
                      <Settings size={16} className="text-zinc-500" />
                      Account settings
                      <ArrowUpRight
                        size={13}
                        className="ml-auto text-zinc-600"
                      />
                    </Link>

                    {logoutError && (
                      <p
                        role="alert"
                        className="px-3 py-2 text-xs leading-5 text-red-300"
                      >
                        {logoutError}
                      </p>
                    )}

                    <button
                      type="button"
                      role="menuitem"
                      onClick={handleLogout}
                      disabled={isLoggingOut}
                      className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-red-300 transition hover:bg-red-400/[0.08] disabled:opacity-50"
                    >
                      <LogOut size={16} />
                      {isLoggingOut ? "Signing out..." : "Sign out"}
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </header>

        <main className="flex-1 p-4 sm:p-6 lg:p-8">{children}</main>

        <footer className="flex min-h-12 items-center justify-between border-t border-white/[0.06] px-4 text-[10px] text-zinc-600 sm:px-6 lg:px-8">
          <span>OpsPilot Operations Platform</span>
          <span className="hidden sm:inline">
            Operational clarity · Accountable workflows
          </span>
          <span className="sm:hidden">v1.0</span>
        </footer>
      </div>
    </div>
  );
}