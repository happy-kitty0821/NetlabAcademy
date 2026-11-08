import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  FlaskConical,
  Network,
  Shield,
  Terminal,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/Button";

export const metadata: Metadata = {
  title: "NetLab Academy — Network simulation and CCNA/CCNP training",
};

export default function HomePage() {
  return (
    <div className="min-h-screen bg-[var(--surface-base)] flex flex-col">
      {/* ── Nav ─────────────────────────────────────────────────────── */}
      <header className="border-b border-[var(--surface-border)] bg-[var(--surface-raised)]">
        <div className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
          <span className="flex items-center gap-2 font-semibold text-sm text-[var(--text-primary)]">
            <Network
              size={16}
              className="text-[var(--accent-primary)]"
              aria-hidden="true"
            />
            NetLab<span className="text-[var(--accent-primary)]">Academy</span>
          </span>
          <nav aria-label="Site navigation" className="flex items-center gap-2">
            <Link
              href="/login"
              className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] px-3 py-1.5 rounded-md hover:bg-[var(--surface-overlay)] transition-colors"
            >
              Sign in
            </Link>
            <Button as="a" href="/register" size="sm">
              Get started
            </Button>
          </nav>
        </div>
      </header>

      <main id="main-content" className="flex-1">
        {/* ── Hero ──────────────────────────────────────────────────── */}
        <section className="relative overflow-hidden border-b border-[var(--surface-border)]">
          {/* Topology grid background */}
          <div
            className="absolute inset-0 pointer-events-none opacity-[0.04]"
            aria-hidden="true"
            style={{
              backgroundImage: `
                linear-gradient(var(--surface-border) 1px, transparent 1px),
                linear-gradient(90deg, var(--surface-border) 1px, transparent 1px)
              `,
              backgroundSize: "40px 40px",
            }}
          />

          <div className="max-w-3xl mx-auto px-6 py-20 relative z-10">
            {/* Label pill */}
            <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full border border-[var(--surface-border)] bg-[var(--surface-overlay)] text-xs text-[var(--text-secondary)] mb-6">
              <span
                className="w-1.5 h-1.5 rounded-full bg-[var(--status-success)]"
                aria-hidden="true"
              />
              Simulator core operational · Phase 0 complete
            </div>

            <h1 className="text-4xl font-semibold text-[var(--text-primary)] leading-tight tracking-tight">
              Learn networking by{" "}
              <span className="text-[var(--accent-primary)]">doing it.</span>
            </h1>
            <p className="mt-4 text-base text-[var(--text-secondary)] max-w-xl leading-relaxed">
              NetLab Academy combines a deterministic software network simulator,
              hands-on topology labs and a structured examination engine — built
              for CCNA and CCNP candidates who want to understand the protocol,
              not just pass a multiple-choice question.
            </p>

            <div className="flex flex-wrap gap-3 mt-8">
              <Button as="a" href="/register" size="lg">
                Start learning
                <ArrowRight size={14} aria-hidden="true" />
              </Button>
              <Button as="a" href="/login" variant="secondary" size="lg">
                Sign in
              </Button>
            </div>
          </div>
        </section>

        {/* ── Feature grid ──────────────────────────────────────────── */}
        <section className="max-w-5xl mx-auto px-6 py-16">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-8">
            Platform capabilities
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map((f) => (
              <FeatureCard key={f.title} {...f} />
            ))}
          </div>
        </section>

        {/* ── Simulator demo trace ──────────────────────────────────── */}
        <section className="border-t border-[var(--surface-border)] bg-[var(--surface-raised)]">
          <div className="max-w-5xl mx-auto px-6 py-14">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-center">
              <div>
                <h2 className="text-xl font-semibold text-[var(--text-primary)]">
                  Every packet is observable.
                </h2>
                <p className="mt-3 text-sm text-[var(--text-secondary)] leading-relaxed">
                  The simulator produces a typed event trace for every frame
                  transmitted. ARP resolution, MAC learning, ICMP echo — each
                  step is recorded with its logical timestamp and available for
                  inspection. Identical topology, seed and inputs always produce
                  the same result.
                </p>
                <ul className="mt-5 space-y-2">
                  {[
                    "Discrete-event engine with logical clock",
                    "Seeded, reproducible packet traces",
                    "ARP, Ethernet forwarding and ICMP implemented",
                    "No raw sockets or host networking",
                  ].map((item) => (
                    <li
                      key={item}
                      className="flex items-start gap-2 text-sm text-[var(--text-secondary)]"
                    >
                      <span
                        className="mt-1.5 w-1 h-1 rounded-full bg-[var(--accent-primary)] shrink-0"
                        aria-hidden="true"
                      />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Trace output mock */}
              <div
                className="rounded-lg overflow-hidden border border-[var(--surface-border)]"
                aria-label="Simulator event trace example"
              >
                <div className="flex items-center gap-1.5 px-3 py-2.5 bg-[var(--terminal-bg)] border-b border-[var(--surface-border)]">
                  {["#f85149", "#d29922", "#3fb950"].map((c, i) => (
                    <span
                      key={i}
                      className="w-2.5 h-2.5 rounded-full"
                      style={{ background: c }}
                      aria-hidden="true"
                    />
                  ))}
                  <span className="ml-2 text-xs text-[var(--text-muted)] font-mono">
                    event trace · seed=42
                  </span>
                </div>
                <pre
                  className="p-4 text-xs font-mono leading-relaxed bg-[var(--terminal-bg)] overflow-x-auto"
                  aria-label="Example simulator event trace output"
                >
                  <TraceLine t={1}  type="ARPRequestSent"    detail="host-a → ff:ff:ff:ff:ff:ff  who-has 192.168.1.2?" />
                  <TraceLine t={2}  type="FrameArrival"      detail="switch-1:Gi0/0 ← host-a" />
                  <TraceLine t={2}  type="MACTableLearned"   detail="switch-1  aa:bb:cc  Gi0/0  vlan 1" />
                  <TraceLine t={2}  type="FrameTransmit"     detail="switch-1:Gi0/1 → host-b (flood)" />
                  <TraceLine t={3}  type="FrameArrival"      detail="host-b:eth0 ← switch-1" />
                  <TraceLine t={3}  type="ARPCacheUpdated"   detail="host-b  192.168.1.1 → aa:bb:cc" />
                  <TraceLine t={3}  type="ARPReplySent"      detail="host-b → aa:bb:cc  192.168.1.2 is-at dd:ee:ff" />
                  <TraceLine t={5}  type="ARPCacheUpdated"   detail="host-a  192.168.1.2 → dd:ee:ff" />
                  <TraceLine t={6}  type="ICMPEchoRequestSent" detail="host-a → host-b  seq=0  id=0xACAD" />
                  <TraceLine t={9}  type="ICMPEchoReplySent" detail="host-b → host-a  seq=0  rtt=3 ticks" />
                </pre>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* ── Footer ────────────────────────────────────────────────── */}
      <footer className="border-t border-[var(--surface-border)] bg-[var(--surface-raised)]">
        <div className="max-w-5xl mx-auto px-6 py-5 flex items-center justify-between text-xs text-[var(--text-muted)]">
          <span>NetLab Academy — independent networking education platform</span>
          <span>Not affiliated with Cisco Systems.</span>
        </div>
      </footer>
    </div>
  );
}

// ── Feature data ──────────────────────────────────────────────────────────────

const FEATURES = [
  {
    icon: Network,
    title: "Software simulator",
    body: "An original discrete-event network model. Ethernet, ARP, ICMP, switching and routing — built from first principles, no Cisco IOS.",
  },
  {
    icon: Terminal,
    title: "Educational CLI",
    body: "A documented Cisco-style command interface mapped to typed operations. Unsupported commands fail explicitly — never silently.",
  },
  {
    icon: FlaskConical,
    title: "Topology labs",
    body: "Build, configure and troubleshoot networks in a visual editor. Each lab instance is isolated, versioned and reproducible.",
  },
  {
    icon: BookOpen,
    title: "Examination engine",
    body: "Timed practice exams, randomised question banks and topic-level performance tracking for CCNA and CCNP curricula.",
  },
  {
    icon: Zap,
    title: "Deterministic replay",
    body: "Every simulation run is seeded. Same topology, same inputs, same seed → same event trace. Labs can be graded on behaviour, not command text.",
  },
  {
    icon: Shield,
    title: "Secure by design",
    body: "The simulator has no host network access, no shell execution, no arbitrary code paths. Student input goes through an allowlisted parser.",
  },
];

function FeatureCard({
  icon: Icon,
  title,
  body,
}: {
  icon: React.ElementType;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--surface-border)] bg-[var(--surface-raised)] p-5">
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center mb-3"
        style={{ background: "var(--surface-overlay)" }}
        aria-hidden="true"
      >
        <Icon size={15} className="text-[var(--accent-primary)]" />
      </div>
      <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1.5">
        {title}
      </h3>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
        {body}
      </p>
    </div>
  );
}

function TraceLine({
  t,
  type,
  detail,
}: {
  t: number;
  type: string;
  detail: string;
}) {
  // Colour-code event types
  const typeColor =
    type.startsWith("ARP")
      ? "text-[var(--status-warning)]"
      : type.startsWith("ICMP")
      ? "text-[var(--status-success)]"
      : type.startsWith("MAC")
      ? "text-[#bf96ff]"
      : "text-[var(--accent-primary)]";

  return (
    <span className="block">
      <span className="text-[var(--text-muted)] select-none">
        {String(t).padStart(3, " ")}  {" "}
      </span>
      <span className={typeColor}>{type.padEnd(22)}</span>
      <span className="text-[var(--text-secondary)]">{detail}</span>
      {"\n"}
    </span>
  );
}
