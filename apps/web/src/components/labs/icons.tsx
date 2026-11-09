/**
 * Network device icons — GNS3 / Cisco Packet Tracer logical style.
 *
 * All icons are self-contained SVG paths with explicit fill/stroke colors
 * passed as props. They do NOT use CSS variables because they are rendered
 * inside an SVG canvas where CSS custom properties do not resolve reliably.
 *
 * Each icon renders at the exact pixel size requested via viewBox scaling.
 * They are designed to be embedded directly inside a parent <svg> using
 * <image> or rendered as standalone <svg> elements outside the canvas.
 */

// ── PC / End-host ─────────────────────────────────────────────────────────────
// Iconic Cisco-style PC: monitor + base.

export function PcIconSVG({
  x = 0,
  y = 0,
  size = 52,
  active = false,
}: {
  x?: number;
  y?: number;
  size?: number;
  active?: boolean;
}) {
  const s = size / 52;
  const bodyColor = "#1c2128";
  const screenColor = "#010409";
  const strokeColor = active ? "#58a6ff" : "#58a6ff";
  const labelLineColor = active ? "#58a6ff" : "#3d5a80";

  return (
    <g transform={`translate(${x - size / 2}, ${y - size / 2}) scale(${s})`}>
      {/* Monitor outer */}
      <rect x="6" y="4" width="40" height="30" rx="2.5"
        fill={bodyColor} stroke={strokeColor} strokeWidth="2" />
      {/* Screen */}
      <rect x="10" y="8" width="32" height="22" rx="1"
        fill={screenColor} />
      {/* Prompt cursor */}
      <text x="13" y="22" fill={labelLineColor}
        fontSize="9" fontFamily="monospace" fontWeight="bold">
        {active ? "_" : ">_"}
      </text>
      {/* Neck */}
      <rect x="22" y="34" width="8" height="5"
        fill={bodyColor} stroke={strokeColor} strokeWidth="1.5" />
      {/* Base */}
      <rect x="14" y="39" width="24" height="4" rx="2"
        fill={bodyColor} stroke={strokeColor} strokeWidth="1.5" />
      {/* Active indicator */}
      {active && (
        <circle cx="26" cy="10" r="2" fill="#3fb950" />
      )}
    </g>
  );
}

// ── Ethernet Switch ────────────────────────────────────────────────────────────
// Cisco-style switch: flat chassis with port LEDs.

export function SwitchIconSVG({
  x = 0,
  y = 0,
  size = 56,
  active = false,
}: {
  x?: number;
  y?: number;
  size?: number;
  active?: boolean;
}) {
  const s = size / 56;
  const strokeColor = active ? "#58a6ff" : "#58a6ff";
  const bodyColor = "#1c2128";
  const portActiveColor = "#3fb950";
  const portInactiveColor = "#484f58";

  return (
    <g transform={`translate(${x - size / 2}, ${y - size / 2}) scale(${s})`}>
      {/* Chassis */}
      <rect x="2" y="16" width="52" height="24" rx="3"
        fill={bodyColor} stroke={strokeColor} strokeWidth="2" />
      {/* Brand stripe */}
      <rect x="2" y="16" width="52" height="6" rx="3"
        fill={active ? "#1d3558" : "#161b22"} />
      {/* Left arrow */}
      <path d="M10 29 L18 29" stroke={strokeColor} strokeWidth="2"
        strokeLinecap="round" />
      <path d="M15 25 L18 29 L15 33" stroke={strokeColor} strokeWidth="2"
        fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* Right arrow */}
      <path d="M46 29 L38 29" stroke={strokeColor} strokeWidth="2"
        strokeLinecap="round" />
      <path d="M41 25 L38 29 L41 33" stroke={strokeColor} strokeWidth="2"
        fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* Port LEDs */}
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <rect key={i}
          x={22 + i * 5} y={28}
          width="3" height="5" rx="0.5"
          fill={active && i < 2 ? portActiveColor : portInactiveColor}
        />
      ))}
    </g>
  );
}

// ── Router ─────────────────────────────────────────────────────────────────────
// Cisco-style router: cylinder circle with arrows.

export function RouterIconSVG({
  x = 0,
  y = 0,
  size = 52,
  active = false,
}: {
  x?: number;
  y?: number;
  size?: number;
  active?: boolean;
}) {
  const s = size / 52;
  const strokeColor = active ? "#58a6ff" : "#58a6ff";
  const fillColor = active ? "#1d3558" : "#1c2128";

  return (
    <g transform={`translate(${x - size / 2}, ${y - size / 2}) scale(${s})`}>
      {/* Outer circle */}
      <circle cx="26" cy="26" r="22"
        fill={fillColor} stroke={strokeColor} strokeWidth="2" />
      {/* Inner ring */}
      <circle cx="26" cy="26" r="14"
        fill="none" stroke={strokeColor} strokeWidth="1" opacity="0.4" />
      {/* Up arrow */}
      <path d="M26 8 L26 16" stroke={strokeColor} strokeWidth="2" strokeLinecap="round" />
      <path d="M22 12 L26 8 L30 12" stroke={strokeColor} strokeWidth="2"
        fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* Right arrow */}
      <path d="M44 26 L36 26" stroke={strokeColor} strokeWidth="2" strokeLinecap="round" />
      <path d="M40 22 L44 26 L40 30" stroke={strokeColor} strokeWidth="2"
        fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* Down arrow */}
      <path d="M26 44 L26 36" stroke={strokeColor} strokeWidth="2" strokeLinecap="round" />
      <path d="M22 40 L26 44 L30 40" stroke={strokeColor} strokeWidth="2"
        fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* Left arrow */}
      <path d="M8 26 L16 26" stroke={strokeColor} strokeWidth="2" strokeLinecap="round" />
      <path d="M12 22 L8 26 L12 30" stroke={strokeColor} strokeWidth="2"
        fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </g>
  );
}
