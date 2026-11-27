import type { Metadata } from "next";
import Link from "next/link";
import { MyLabsSection } from "./MyLabsSection";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Play, Plus } from "lucide-react";

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

// ── Page ──────────────────────────────────────────────────────────────────────
// Dashboard layout: the user's labs first (tiles or table), then sample labs
// as a compact table. "New lab" opens an empty workspace.

export default function LabsPage() {
  const samples = [...LABS].sort((a, b) =>
    Number(b.status === "available") - Number(a.status === "available"));

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-[var(--surface-border)] pb-4">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">Labs</h1>
          <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
            Build topologies, cable devices port to port, and work on their consoles.
          </p>
        </div>
        <Link href="/labs/workspace?new=1">
          <Button size="sm">
            <Plus size={12} aria-hidden="true" />
            New lab
          </Button>
        </Link>
      </header>

      <MyLabsSection />

      <section aria-labelledby="sample-labs-heading" className="space-y-3">
        <div>
          <h2 id="sample-labs-heading" className="text-sm font-semibold text-[var(--text-primary)]">
            Sample labs
          </h2>
          <p className="text-xs text-[var(--text-secondary)]">Guided exercises for CCNA learners.</p>
        </div>
        <div className="overflow-x-auto rounded-md border border-[var(--surface-border)] bg-[var(--surface-raised)]">
          <table className="w-full min-w-[40rem] text-left text-xs">
            <thead className="bg-[var(--surface-overlay)] text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-2 font-semibold">Lab</th>
                <th className="px-3 py-2 font-semibold">Topic</th>
                <th className="px-3 py-2 font-semibold">Level</th>
                <th className="px-3 py-2 font-semibold">Time</th>
                <th className="px-4 py-2"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {samples.map((lab) => <SampleRow key={lab.id} lab={lab} />)}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function SampleRow({ lab }: { lab: LabDefinition }) {
  const available = lab.status === "available";
  return (
    <tr className={"border-t border-[var(--surface-border)] align-top " + (available ? "hover:bg-[var(--surface-overlay)]" : "")}>
      <td className="px-4 py-2.5">
        <p className={"font-medium " + (available ? "text-[var(--text-primary)]" : "text-[var(--text-muted)]")}>{lab.title}</p>
        <p className="mt-0.5 max-w-xl text-[var(--text-secondary)]">{lab.description}</p>
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-[var(--text-secondary)]">{lab.topic}</td>
      <td className="whitespace-nowrap px-3 py-2.5">
        <Badge variant={DIFFICULTY_BADGE[lab.difficulty]}>{lab.difficulty}</Badge>
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-[var(--text-secondary)]">{lab.duration}</td>
      <td className="whitespace-nowrap px-4 py-2 text-right">
        {available ? (
          <Link href={`/labs/workspace?lab=${lab.id}`}>
            <Button size="sm" variant="secondary">
              <Play size={12} aria-hidden="true" />
              Start
            </Button>
          </Link>
        ) : (
          <span className="text-[11px] text-[var(--text-muted)]">Coming soon</span>
        )}
      </td>
    </tr>
  );
}
