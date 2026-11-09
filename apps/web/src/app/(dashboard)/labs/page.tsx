import type { Metadata } from "next";
import Link from "next/link";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  BookOpen,
  ChevronRight,
  Clock,
  FlaskConical,
  Lock,
  Network,
  Play,
  Star,
  Wifi,
} from "lucide-react";

export const metadata: Metadata = { title: "Labs" };

// ── Static lab catalog (placeholder until the lab-lifecycle spec is built) ────

const LABS: LabDefinition[] = [
  {
    id: "lab-01-basic-connectivity",
    title: "Basic Ethernet Connectivity",
    topic: "Switching",
    level: "CCNA",
    difficulty: "beginner",
    duration: "15 min",
    description:
      "Connect two PCs through a Catalyst 2960 switch. Configure IP addressing, verify ARP resolution, and run ping tests to confirm end-to-end connectivity.",
    objectives: [
      "Configure IPv4 addresses on two end hosts",
      "Observe ARP request and reply in the packet trace",
      "Verify MAC address learning on the switch",
      "Confirm successful ICMP echo exchange",
    ],
    tags: ["ARP", "ICMP", "Switching", "IPv4"],
    status: "available",
    completed: false,
  },
  {
    id: "lab-02-mac-learning",
    title: "Switch MAC Address Learning",
    topic: "Switching",
    level: "CCNA",
    difficulty: "beginner",
    duration: "20 min",
    description:
      "Explore how an Ethernet switch builds its MAC address table. Add multiple hosts, generate traffic, and inspect the MAC table using show mac address-table.",
    objectives: [
      "Explain the MAC learning process",
      "Use show mac address-table to verify learned entries",
      "Observe unknown-unicast flooding before learning",
      "Verify known-unicast forwarding after learning",
    ],
    tags: ["MAC", "Switching", "Frame forwarding"],
    status: "available",
    completed: false,
  },
  {
    id: "lab-03-vlans",
    title: "VLAN Segmentation",
    topic: "VLANs",
    level: "CCNA",
    difficulty: "intermediate",
    duration: "30 min",
    description:
      "Create VLANs on a switch, assign access ports, and verify that hosts in different VLANs cannot communicate without a router.",
    objectives: [
      "Create VLANs 10 and 20",
      "Assign switch ports to access VLANs",
      "Verify isolation between VLANs",
      "Document the VLAN configuration",
    ],
    tags: ["VLAN", "Access port", "Segmentation"],
    status: "coming-soon",
    completed: false,
  },
  {
    id: "lab-04-static-routing",
    title: "Static Routing Fundamentals",
    topic: "Routing",
    level: "CCNA",
    difficulty: "intermediate",
    duration: "35 min",
    description:
      "Connect two LANs through a router. Configure static routes and verify inter-network reachability using ping and traceroute.",
    objectives: [
      "Configure router interfaces with IP addresses",
      "Add static routes for remote networks",
      "Verify routing table with show ip route",
      "Test connectivity between subnets",
    ],
    tags: ["Static routing", "IPv4", "Router"],
    status: "coming-soon",
    completed: false,
  },
];

type LabDifficulty = "beginner" | "intermediate" | "advanced";
type LabStatus = "available" | "coming-soon" | "locked";

interface LabDefinition {
  id: string;
  title: string;
  topic: string;
  level: string;
  difficulty: LabDifficulty;
  duration: string;
  description: string;
  objectives: string[];
  tags: string[];
  status: LabStatus;
  completed: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const DIFFICULTY_BADGE: Record<LabDifficulty, "success" | "warning" | "error"> = {
  beginner:     "success",
  intermediate: "warning",
  advanced:     "error",
};

const TOPIC_ICON: Record<string, React.ElementType> = {
  Switching: Network,
  VLANs:     Network,
  Routing:   Network,
  default:   FlaskConical,
};

// ── Page ──────────────────────────────────────────────────────────────────────

export default function LabsPage() {
  const available = LABS.filter((l) => l.status === "available");
  const comingSoon = LABS.filter((l) => l.status === "coming-soon");

  return (
    <div className="max-w-5xl mx-auto space-y-8">

      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">Lab Catalog</h1>
          <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
            Hands-on networking labs for CCNA and CCNP learners.
          </p>
        </div>
        <Link href="/labs/workspace">
          <Button size="sm" variant="secondary">
            <Network size={12} aria-hidden="true" />
            Open free workspace
          </Button>
        </Link>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Available now", value: available.length, color: "text-[var(--status-success)]" },
          { label: "Coming soon", value: comingSoon.length, color: "text-[var(--status-warning)]" },
          { label: "Completed",   value: LABS.filter((l) => l.completed).length, color: "text-[var(--accent-primary)]" },
        ].map((s) => (
          <Card key={s.label}>
            <CardBody className="py-3 px-4">
              <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">{s.label}</p>
            </CardBody>
          </Card>
        ))}
      </div>

      {/* Available labs */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-4">
          Available now
        </h2>
        <div className="grid grid-cols-1 gap-4">
          {available.map((lab) => (
            <LabCard key={lab.id} lab={lab} />
          ))}
        </div>
      </section>

      {/* Coming soon */}
      {comingSoon.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-4">
            Coming soon
          </h2>
          <div className="grid grid-cols-1 gap-4">
            {comingSoon.map((lab) => (
              <LabCard key={lab.id} lab={lab} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ── Lab card ──────────────────────────────────────────────────────────────────

function LabCard({ lab }: { lab: LabDefinition }) {
  const Icon = TOPIC_ICON[lab.topic] ?? TOPIC_ICON.default;
  const isAvailable = lab.status === "available";
  const isComingSoon = lab.status === "coming-soon";

  return (
    <Card className={isComingSoon ? "opacity-70" : ""}>
      <CardBody>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          {/* Left: icon + info */}
          <div className="flex items-start gap-4 min-w-0 flex-1">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
              style={{ background: isAvailable ? "var(--accent-subtle)" : "var(--surface-overlay)" }}
              aria-hidden="true"
            >
              {lab.completed ? (
                <Star size={16} className="text-[var(--status-success)]" />
              ) : isComingSoon ? (
                <Lock size={16} className="text-[var(--text-muted)]" />
              ) : (
                <Icon size={16} className="text-[var(--accent-primary)]" />
              )}
            </div>

            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                  {lab.title}
                </h3>
                <Badge variant={DIFFICULTY_BADGE[lab.difficulty]}>
                  {lab.difficulty}
                </Badge>
                {lab.completed && (
                  <Badge variant="success">completed</Badge>
                )}
                {isComingSoon && (
                  <Badge variant="default">coming soon</Badge>
                )}
              </div>

              <p className="text-xs text-[var(--text-secondary)] mb-2 leading-relaxed">
                {lab.description}
              </p>

              {/* Objectives */}
              <ul className="hidden sm:flex flex-col gap-0.5 mb-2">
                {lab.objectives.slice(0, 2).map((obj) => (
                  <li key={obj} className="flex items-start gap-1.5 text-xs text-[var(--text-muted)]">
                    <span className="mt-1.5 w-1 h-1 rounded-full bg-[var(--accent-primary)] shrink-0" aria-hidden="true" />
                    {obj}
                  </li>
                ))}
              </ul>

              {/* Meta row */}
              <div className="flex items-center gap-3 flex-wrap text-xs text-[var(--text-muted)]">
                <span className="flex items-center gap-1">
                  <BookOpen size={11} aria-hidden="true" />
                  {lab.level}
                </span>
                <span className="flex items-center gap-1">
                  <Clock size={11} aria-hidden="true" />
                  {lab.duration}
                </span>
                <span className="flex items-center gap-1">
                  <Wifi size={11} aria-hidden="true" />
                  {lab.topic}
                </span>
              </div>
            </div>
          </div>

          {/* Right: action */}
          <div className="flex items-center">
            {isAvailable ? (
              <Link href={`/labs/workspace?lab=${lab.id}`}>
                <Button size="sm">
                  <Play size={12} aria-hidden="true" />
                  {lab.completed ? "Retry" : "Start lab"}
                  <ChevronRight size={12} aria-hidden="true" />
                </Button>
              </Link>
            ) : (
              <Button size="sm" variant="secondary" disabled>
                <Lock size={12} aria-hidden="true" />
                Coming soon
              </Button>
            )}
          </div>
        </div>
      </CardBody>
    </Card>
  );
}
