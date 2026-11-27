/**
 * AuthShell — layout for the sign-in and registration pages.
 *
 * Light theme matching the app. Two columns on large screens: the form on
 * the left, a quiet network-topology illustration on the right (hidden on
 * small screens). Motion is limited to a short staggered entrance and one
 * slow packet along the illustration's links; both are disabled when the
 * user prefers reduced motion (see .auth-* rules in globals.css).
 */

import Link from "next/link";
import { Network } from "lucide-react";

interface AuthShellProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

const rise = (ms: number) => ({ "--auth-delay": `${ms}ms` }) as React.CSSProperties;

export function AuthShell({ title, subtitle, children, footer }: AuthShellProps) {
  return (
    <div className="min-h-screen grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] bg-[var(--surface-raised)]">
      {/* ── Form column ─────────────────────────────────────────────── */}
      <main className="flex flex-col px-6 py-8 sm:px-12">
        <Link
          href="/"
          className="auth-rise inline-flex items-center gap-2 self-start text-sm font-semibold text-[var(--text-primary)] no-underline"
          style={rise(0)}
        >
          <span className="w-7 h-7 rounded-md flex items-center justify-center bg-[var(--accent-primary)]">
            <Network size={14} className="text-white" aria-hidden="true" />
          </span>
          NetLab<span className="text-[var(--accent-primary)] -ml-1.5">Academy</span>
        </Link>

        <div className="flex-1 flex items-center">
          <div className="w-full max-w-[360px] mx-auto py-10">
            <div className="auth-rise mb-7" style={rise(60)}>
              <h1 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
                {title}
              </h1>
              {subtitle && (
                <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">{subtitle}</p>
              )}
            </div>

            <div className="auth-rise" style={rise(120)}>
              {children}
            </div>

            {footer && (
              <p className="auth-rise mt-6 text-sm text-[var(--text-secondary)]" style={rise(200)}>
                {footer}
              </p>
            )}
          </div>
        </div>

        <p className="text-xs text-[var(--text-muted)]">
          Independent educational platform. Not affiliated with Cisco Systems.
        </p>
      </main>

      {/* ── Illustration column (large screens only) ────────────────── */}
      <aside
        aria-hidden="true"
        className="hidden lg:flex flex-col justify-center gap-10 px-14 bg-[var(--surface-base)] border-l border-[var(--surface-border)]"
      >
        <TopologyIllustration />
        <ul className="auth-rise space-y-4 max-w-md" style={rise(260)}>
          {[
            ["Build topologies", "Drag switches, routers and PCs onto a canvas and cable them up."],
            ["Configure with a Cisco-style CLI", "VLANs, trunks, static routes and router-on-a-stick."],
            ["Trace every packet", "Step through ARP, ICMP and switching decisions one event at a time."],
          ].map(([heading, text]) => (
            <li key={heading} className="flex gap-3">
              <span className="mt-[7px] w-1.5 h-1.5 shrink-0 bg-[var(--accent-primary)]" />
              <div>
                <p className="text-sm font-medium text-[var(--text-primary)]">{heading}</p>
                <p className="text-sm text-[var(--text-secondary)]">{text}</p>
              </div>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}

/** Two PCs, two switches and a router, with one packet looping slowly. */
function TopologyIllustration() {
  // Single path through all links so one dash can travel the whole topology.
  const route = "M70 70 H190 V150 H310 V230 H430 V310 H550";
  const device = (x: number, y: number, label: string, kind: "pc" | "switch" | "router") => (
    <g transform={`translate(${x - 30} ${y - 18})`}>
      <rect width="60" height="36" rx="6" fill="#ffffff" stroke="#d0d7de" />
      {kind === "pc" && <rect x="20" y="9" width="20" height="13" rx="1.5" fill="none" stroke="#656d76" />}
      {kind === "switch" && (
        <g stroke="#0969da" strokeWidth="1.5">
          <path d="M18 14 H42 M18 22 H42" />
          <path d="M38 11 L42 14 L38 17 M22 19 L18 22 L22 25" fill="none" />
        </g>
      )}
      {kind === "router" && <circle cx="30" cy="16" r="7" fill="none" stroke="#1a7f37" strokeWidth="1.5" />}
      <text x="30" y="31" textAnchor="middle" fontSize="7" fill="#656d76" fontFamily="ui-monospace,monospace">{label}</text>
    </g>
  );

  return (
    <svg viewBox="0 0 620 380" className="auth-rise w-full max-w-xl" style={rise(180)}>
      <defs>
        <pattern id="auth-grid" width="20" height="20" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="1" fill="#d8dee4" />
        </pattern>
      </defs>
      <rect width="620" height="380" fill="url(#auth-grid)" />
      <path d={route} fill="none" stroke="#c5ced8" strokeWidth="1.5" />
      <path d={route} fill="none" stroke="#0969da" strokeWidth="3" strokeLinecap="round" className="auth-packet" />
      {device(70, 70, "PC-A", "pc")}
      {device(190, 150, "SW1", "switch")}
      {device(310, 150, "R1", "router")}
      {device(430, 310, "SW2", "switch")}
      {device(550, 310, "PC-B", "pc")}
      <text x="70" y="108" textAnchor="middle" fontSize="9" fill="#9198a1" fontFamily="ui-monospace,monospace">192.168.10.10</text>
      <text x="550" y="348" textAnchor="middle" fontSize="9" fill="#9198a1" fontFamily="ui-monospace,monospace">192.168.20.10</text>
    </svg>
  );
}
