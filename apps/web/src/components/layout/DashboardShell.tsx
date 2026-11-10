import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import type { User } from "@/types/api";

interface DashboardShellProps {
  user: User | null;
  title?: string;
  onLogout?: () => void;
  children: React.ReactNode;
  fullscreen?: boolean;  // suppresses padding for workspace pages
}

export function DashboardShell({
  user,
  title,
  onLogout,
  children,
  fullscreen = false,
}: DashboardShellProps) {
  return (
    <div className="flex h-screen overflow-hidden bg-[var(--surface-base)]">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <TopBar user={user} title={title} onLogout={onLogout} />
        <main
          id="main-content"
          className={`flex-1 min-h-0 ${fullscreen ? "overflow-hidden" : "overflow-y-auto p-6"}`}
          tabIndex={-1}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
