"use client";

import { Bell, LogOut, User } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import type { User as UserType } from "@/types/api";

interface TopBarProps {
  user:      UserType | null;
  onLogout?: () => void;
  title?:    string;
}

export function TopBar({ user, onLogout, title }: TopBarProps) {
  return (
    <header className="h-14 flex items-center justify-between px-6 bg-white border-b border-[#d0d7de] sticky top-0 z-10">
      <div className="flex items-center gap-3">
        {title && <h1 className="text-sm font-semibold text-[#1f2328]">{title}</h1>}
      </div>

      <div className="flex items-center gap-2">
        <button
          className="p-2 rounded-md text-[#656d76] hover:text-[#1f2328] hover:bg-[#f0f2f4] transition-colors"
          aria-label="Notifications"
        >
          <Bell size={15} />
        </button>

        {user && (
          <div className="flex items-center gap-2 pl-2 border-l border-[#d0d7de]">
            <div
              className="w-7 h-7 rounded-full flex items-center justify-center bg-[#ddf4ff] text-[#0969da]"
              aria-hidden="true"
            >
              <User size={13} />
            </div>
            <div className="hidden sm:flex flex-col">
              <span className="text-xs font-medium text-[#1f2328] leading-tight">
                {user.full_name || user.email}
              </span>
              <Badge variant={user.role as "admin" | "instructor" | "student"} className="mt-0.5">
                {user.role}
              </Badge>
            </div>
            {onLogout && (
              <Button variant="ghost" size="sm" onClick={onLogout} aria-label="Log out" className="ml-1">
                <LogOut size={13} />
                <span className="hidden sm:inline">Log out</span>
              </Button>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
