"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  BookOpen, FlaskConical, LayoutDashboard,
  Network, Settings, Users, ChevronLeft, ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem { label: string; href: string; icon: React.ElementType; }

const NAV: NavItem[] = [
  { label: "Dashboard", href: "/dashboard",     icon: LayoutDashboard },
  { label: "Courses",   href: "/courses",        icon: BookOpen },
  { label: "Labs",      href: "/labs",           icon: FlaskConical },
  { label: "Workspace", href: "/labs/workspace", icon: Network },
];

const BOTTOM_NAV: NavItem[] = [
  { label: "Devices",  href: "/admin/devices", icon: Network },
  { label: "Users",    href: "/admin/users",   icon: Users },
  { label: "Settings", href: "/settings",      icon: Settings },
];

export function Sidebar() {
  const pathname    = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={cn(
        "flex flex-col shrink-0 h-screen sticky top-0 bg-white border-r border-[#d0d7de] transition-all duration-200",
        collapsed ? "w-12" : "w-56"
      )}
    >
      {/* Logo / collapse button */}
      <div className="h-14 flex items-center justify-between px-3 border-b border-[#d0d7de] overflow-hidden">
        {!collapsed && (
          <span className="flex items-center gap-2 font-semibold text-[#1f2328] text-sm truncate">
            <Network size={16} className="text-[#0969da] shrink-0" />
            NetLab<span className="text-[#0969da]">Academy</span>
          </span>
        )}
        {collapsed && <Network size={16} className="text-[#0969da] mx-auto" />}
        <button
          onClick={() => setCollapsed((v) => !v)}
          className={cn(
            "p-1.5 rounded-md text-[#656d76] hover:text-[#1f2328] hover:bg-[#f0f2f4] transition-colors shrink-0",
            collapsed && "mx-auto"
          )}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>

      {/* Primary nav */}
      <nav aria-label="Main navigation" className="flex-1 overflow-y-auto py-3 px-2">
        <ul role="list" className="space-y-0.5">
          {NAV.map((item) => (
            <li key={item.href}>
              <NavLink item={item} pathname={pathname} collapsed={collapsed} />
            </li>
          ))}
        </ul>
      </nav>

      {/* Bottom nav */}
      <div className="border-t border-[#d0d7de] py-3 px-2">
        <ul role="list" className="space-y-0.5">
          {BOTTOM_NAV.map((item) => (
            <li key={item.href}>
              <NavLink item={item} pathname={pathname} collapsed={collapsed} />
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}

function NavLink({
  item, pathname, collapsed,
}: {
  item:      NavItem;
  pathname:  string;
  collapsed: boolean;
}) {
  const active = item.href === "/labs"
    ? pathname === "/labs"
    : pathname === item.href || pathname.startsWith(item.href + "/");
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      title={collapsed ? item.label : undefined}
      className={cn(
        "flex items-center gap-3 px-2 py-2 text-sm rounded-md transition-colors duration-100",
        collapsed ? "justify-center" : "",
        active
          ? "bg-[#ddf4ff] text-[#0969da] font-medium"
          : "text-[#656d76] hover:text-[#1f2328] hover:bg-[#f0f2f4]"
      )}
    >
      <Icon size={15} aria-hidden="true" className="shrink-0" />
      {!collapsed && item.label}
    </Link>
  );
}
