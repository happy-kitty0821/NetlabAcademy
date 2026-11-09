/**
 * Network device icons — GNS3/Cisco Packet Tracer style.
 *
 * Clean, flat SVG icons drawn at 48x48 viewport.  These are the standard
 * logical representations used in networking education:
 *  - PC: monitor with screen
 *  - Switch: chassis with ports and arrows
 *  - Router: circle with directional arrows
 *
 * Each icon accepts a size prop and className for styling.
 */

interface IconProps {
  size?: number;
  className?: string;
}

// ── PC / End Host ─────────────────────────────────────────────────────────────

export function PcIcon({ size = 48, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      {/* Monitor body */}
      <rect x="8" y="6" width="32" height="24" rx="2" fill="var(--surface-overlay)" stroke="var(--accent-primary)" strokeWidth="1.5" />
      {/* Screen inner */}
      <rect x="11" y="9" width="26" height="18" rx="1" fill="var(--surface-base)" />
      {/* Screen content lines */}
      <line x1="14" y1="13" x2="26" y2="13" stroke="var(--accent-primary)" strokeWidth="1" opacity="0.6" />
      <line x1="14" y1="17" x2="30" y2="17" stroke="var(--accent-primary)" strokeWidth="1" opacity="0.4" />
      <line x1="14" y1="21" x2="22" y2="21" stroke="var(--accent-primary)" strokeWidth="1" opacity="0.4" />
      {/* Stand */}
      <rect x="20" y="30" width="8" height="4" fill="var(--surface-overlay)" stroke="var(--accent-primary)" strokeWidth="1" />
      {/* Base */}
      <rect x="14" y="34" width="20" height="3" rx="1" fill="var(--surface-overlay)" stroke="var(--accent-primary)" strokeWidth="1" />
    </svg>
  );
}

// ── Switch ────────────────────────────────────────────────────────────────────

export function SwitchIcon({ size = 48, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      {/* Chassis */}
      <rect x="4" y="14" width="40" height="20" rx="2" fill="var(--surface-overlay)" stroke="var(--accent-primary)" strokeWidth="1.5" />
      {/* Top label bar */}
      <rect x="4" y="14" width="40" height="5" rx="2" fill="var(--accent-primary)" opacity="0.15" />
      {/* Bidirectional arrows (switching) */}
      <path d="M12 24 L20 24 M17 21 L20 24 L17 27" stroke="var(--accent-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <path d="M36 24 L28 24 M31 21 L28 24 L31 27" stroke="var(--accent-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      {/* Ports (bottom row) */}
      <rect x="8" y="31" width="4" height="3" rx="0.5" fill="var(--accent-primary)" opacity="0.5" />
      <rect x="14" y="31" width="4" height="3" rx="0.5" fill="var(--accent-primary)" opacity="0.5" />
      <rect x="20" y="31" width="4" height="3" rx="0.5" fill="var(--accent-primary)" opacity="0.5" />
      <rect x="26" y="31" width="4" height="3" rx="0.5" fill="var(--accent-primary)" opacity="0.5" />
      <rect x="32" y="31" width="4" height="3" rx="0.5" fill="var(--accent-primary)" opacity="0.5" />
      <rect x="38" y="31" width="4" height="3" rx="0.5" fill="var(--accent-primary)" opacity="0.5" />
    </svg>
  );
}

// ── Router ────────────────────────────────────────────────────────────────────

export function RouterIcon({ size = 48, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      {/* Outer circle */}
      <circle cx="24" cy="24" r="18" fill="var(--surface-overlay)" stroke="var(--accent-primary)" strokeWidth="1.5" />
      {/* Inner circle */}
      <circle cx="24" cy="24" r="12" fill="var(--surface-base)" stroke="var(--accent-primary)" strokeWidth="0.75" opacity="0.5" />
      {/* Four directional arrows (routing) */}
      {/* Up */}
      <path d="M24 10 L24 18 M21 13 L24 10 L27 13" stroke="var(--accent-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      {/* Right */}
      <path d="M38 24 L30 24 M35 21 L38 24 L35 27" stroke="var(--accent-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      {/* Down */}
      <path d="M24 38 L24 30 M21 35 L24 38 L27 35" stroke="var(--accent-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      {/* Left */}
      <path d="M10 24 L18 24 M13 21 L10 24 L13 27" stroke="var(--accent-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

// ── Dispatcher ─────────────────────────────────────────────────────────────────

export function DeviceIcon({
  model,
  size,
  className,
}: {
  model: "host" | "switch" | "router";
  size?: number;
  className?: string;
}) {
  if (model === "switch") return <SwitchIcon size={size} className={className} />;
  if (model === "router") return <RouterIcon size={size} className={className} />;
  return <PcIcon size={size} className={className} />;
}
