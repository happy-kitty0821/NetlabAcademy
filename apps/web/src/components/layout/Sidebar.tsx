"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, FlaskConical, LayoutDashboard, Network, Settings, Users } from "lucide-react";
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
  const pathname = usePathname();
  return (
    <aside className={cn(
      "flex flex-col w-56 shrink-0 h-screen sticky top-0",
      "bg-white border-r border-[#d0d7de]"
    )}>
      <div className="h-14 flex items-center px-5 border-b border-[#d0d7de]">
        <span className="flex items-center gap-2.5 font-semibold text-[#1f2328]">
          <Network size={18} className="text-[#0969da]" aria-hidden="true" />
          NetLab<span className="text-[#0969da]">Academy</span>
        </span>
      </div>

      <nav aria-label="Main navigation" className="flex-1 overflow-y-auto py-3 px-2">
        <ul role="list" className="space-y-0.5">
          {NAV.map((item) => <li key={item.href}><NavLink item={item} pathname={pathname} /></li>)}
        </ul>
      </nav>

      <div className="border-t border-[#d0d7de] py-3 px-2">
        <ul role="list" className="space-y-0.5">
          {BOTTOM_NAV.map((item) => <li key={item.href}><NavLink item={item} pathname={pathname} /></li>)}
        </ul>
      </div>
    </aside>
  );
}

function NavLink({ item, pathname }: { item: NavItem; pathname: string }) {
  const active = item.href === "/labs"
    ? pathname === "/labs"
    : pathname === item.href || pathname.startsWith(item.href + "/");
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 px-3 py-2 text-sm rounded-md transition-colors duration-100",
        active
          ? "bg-[#ddf4ff] text-[#0969da] font-medium"
          : "text-[#656d76] hover:text-[#1f2328] hover:bg-[#f0f2f4]"
      )}
    >
      <Icon size={15} aria-hidden="true" />
      {item.label}
    </Link>
  );
}
