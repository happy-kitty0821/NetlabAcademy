import type { Metadata } from "next";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import {
  BookOpen,
  CheckCircle2,
  Clock,
  FlaskConical,
  Network,
  TrendingUp,
} from "lucide-react";

export const metadata: Metadata = { title: "Dashboard" };

// ── Placeholder stat data ────────────────────────────────────────────────────
// These will be replaced by API data once the courses/labs specs are implemented.

const STATS = [
  {
    label: "Enrolled courses",
    value: "—",
    icon: BookOpen,
    color: "text-[var(--accent-primary)]",
  },
  {
    label: "Labs completed",
    value: "—",
    icon: FlaskConical,
    color: "text-[var(--status-success)]",
  },
  {
    label: "Exams taken",
    value: "—",
    icon: CheckCircle2,
    color: "text-[var(--status-warning)]",
  },
  {
    label: "Hours practised",
    value: "—",
    icon: Clock,
    color: "text-[var(--text-secondary)]",
  },
];

const ACTIVITY: { label: string; time: string; badge: string }[] = [];

export default function DashboardPage() {
  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Page heading */}
      <div>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">
          Overview
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Your learning progress at a glance.
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {STATS.map((stat) => {
          const Icon = stat.icon;
          return (
            <Card key={stat.label}>
              <CardBody className="flex items-center gap-3 py-4">
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                  style={{ background: "var(--surface-overlay)" }}
                  aria-hidden="true"
                >
                  <Icon size={16} className={stat.color} />
                </div>
                <div className="min-w-0">
                  <p className="text-xl font-semibold text-[var(--text-primary)] leading-none">
                    {stat.value}
                  </p>
                  <p className="text-xs text-[var(--text-secondary)] mt-0.5 truncate">
                    {stat.label}
                  </p>
                </div>
              </CardBody>
            </Card>
          );
        })}
      </div>

      {/* Two-column lower section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Recent activity */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                Recent activity
              </h2>
            </CardHeader>
            <CardBody>
              {ACTIVITY.length === 0 ? (
                <EmptyState
                  icon={TrendingUp}
                  message="No activity yet. Enrol in a course or launch a lab to get started."
                />
              ) : (
                <ul role="list" className="space-y-3">
                  {ACTIVITY.map((a, i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-[var(--text-primary)]">
                        {a.label}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-[var(--text-muted)]">
                          {a.time}
                        </span>
                        <Badge>{a.badge}</Badge>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>

        {/* Quick links */}
        <div>
          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                Jump to
              </h2>
            </CardHeader>
            <CardBody className="flex flex-col gap-2">
              <QuickLink
                href="/labs"
                icon={FlaskConical}
                label="Open lab workspace"
              />
              <QuickLink
                href="/courses"
                icon={BookOpen}
                label="Browse courses"
              />
              <QuickLink
                href="/topology"
                icon={Network}
                label="Topology editor"
              />
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function EmptyState({
  icon: Icon,
  message,
}: {
  icon: React.ElementType;
  message: string;
}) {
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center">
      <Icon
        size={20}
        className="text-[var(--text-muted)]"
        aria-hidden="true"
      />
      <p className="text-sm text-[var(--text-secondary)] max-w-xs">{message}</p>
    </div>
  );
}

function QuickLink({
  href,
  icon: Icon,
  label,
}: {
  href: string;
  icon: React.ElementType;
  label: string;
}) {
  return (
    <a
      href={href}
      className="flex items-center gap-2.5 px-3 py-2.5 rounded-md text-sm
        text-[var(--text-secondary)] hover:text-[var(--text-primary)]
        hover:bg-[var(--surface-overlay)] transition-colors duration-100"
    >
      <Icon size={14} className="text-[var(--accent-primary)]" aria-hidden="true" />
      {label}
    </a>
  );
}
