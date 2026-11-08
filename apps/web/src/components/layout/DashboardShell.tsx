import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import type { User } from "@/types/api";

interface DashboardShellProps {
  user: User | null;
  title?: string;
  onLogout?: () => void;
  children: React.ReactNode;
}

/**
 * The persistent authenticated shell: sidebar + top bar + scrollable content.
 * Wrap every authenticated page in this component.
 */
export function DashboardShell({
  user,
  title,
  onLogout,
  children,
}: DashboardShellProps) {
  return (
    <div className="flex h-screen overflow-hidden bg-[var(--surface-base)]">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <TopBar user={user} title={title} onLogout={onLogout} />
        <main
          id="main-content"
          className="flex-1 overflow-y-auto p-6"
          tabIndex={-1}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
