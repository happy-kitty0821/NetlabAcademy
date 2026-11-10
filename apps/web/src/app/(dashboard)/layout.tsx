"use client";

/**
 * Authenticated route group layout.
 *
 * Uses the auth context to pass the real user to the DashboardShell and
 * wraps all child pages in AuthGuard so unauthenticated visitors are
 * redirected to /login.
 */

import { useRouter, usePathname } from "next/navigation";
import { DashboardShell } from "@/components/layout/DashboardShell";
import { AuthGuard } from "@/components/auth/AuthGuard";
import { useAuth } from "@/lib/auth-context";

// Map pathname -> page title shown in the TopBar.
const TITLES: Record<string, string> = {
  "/dashboard": "Overview",
  "/courses": "Courses",
  "/labs": "Labs",
  "/topology": "Topology Editor",
  "/admin/users": "User Management",
  "/settings": "Settings",
};

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const title = TITLES[pathname] ?? "";
  const isWorkspace = pathname === "/labs/workspace" || pathname.startsWith("/labs/workspace");

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <AuthGuard>
      <DashboardShell
        user={user}
        title={isWorkspace ? "" : title}
        onLogout={handleLogout}
        fullscreen={isWorkspace}
      >
        {children}
      </DashboardShell>
    </AuthGuard>
  );
}
