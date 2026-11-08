"use client";

import { Bell, LogOut, User } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import type { User as UserType } from "@/types/api";
import { cn } from "@/lib/utils";

interface TopBarProps {
  user: UserType | null;
  onLogout?: () => void;
  title?: string;
}

export function TopBar({ user, onLogout, title }: TopBarProps) {
  return (
    <header
      className={cn(
        "h-14 flex items-center justify-between px-6",
        "bg-[var(--surface-raised)] border-b border-[var(--surface-border)]",
        "sticky top-0 z-10"
      )}
    >
      {/* Page title */}
      <div className="flex items-center gap-3">
        {title && (
          <h1 className="text-sm font-semibold text-[var(--text-primary)]">
            {title}
          </h1>
        )}
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-2">
        {/* Notification bell — placeholder for future feature */}
        <button
          className={cn(
            "p-2 rounded-md text-[var(--text-secondary)]",
            "hover:text-[var(--text-primary)] hover:bg-[var(--surface-overlay)]",
            "transition-colors duration-100"
          )}
          aria-label="Notifications"
        >
          <Bell size={15} aria-hidden="true" />
        </button>

        {/* User info */}
        {user && (
          <div className="flex items-center gap-2 pl-2 border-l border-[var(--surface-border)]">
            <div className="flex items-center gap-2">
              <div
                className={cn(
                  "w-7 h-7 rounded-full flex items-center justify-center",
                  "bg-[var(--accent-subtle)] text-[var(--accent-primary)]"
                )}
                aria-hidden="true"
              >
                <User size={13} />
              </div>
              <div className="hidden sm:flex flex-col">
                <span className="text-xs font-medium text-[var(--text-primary)] leading-tight">
                  {user.full_name || user.email}
                </span>
                <Badge
                  variant={user.role as "admin" | "instructor" | "student"}
                  className="mt-0.5"
                >
                  {user.role}
                </Badge>
              </div>
            </div>
            {onLogout && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onLogout}
                aria-label="Log out"
                className="ml-1"
              >
                <LogOut size={13} aria-hidden="true" />
                <span className="hidden sm:inline">Log out</span>
              </Button>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
