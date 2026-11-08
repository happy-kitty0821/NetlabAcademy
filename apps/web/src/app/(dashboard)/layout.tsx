/**
 * Authenticated route group layout.
 *
 * Auth guard is intentionally left as a client-side redirect for now
 * (the platform is not yet on a production deployment). A middleware-based
 * guard will be added in the auth-rbac spec.
 */
import { DashboardShell } from "@/components/layout/DashboardShell";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // user and onLogout will be wired to a context/store once the auth
  // feature spec is implemented. For scaffold purposes, null is safe.
  return (
    <DashboardShell user={null} title="">
      {children}
    </DashboardShell>
  );
}
