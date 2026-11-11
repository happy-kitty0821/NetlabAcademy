"use client";

/**
 * Custom React Flow node types — Cisco Packet Tracer logical icon style.
 *
 * All icons are pure inline SVG paths. No foreignObject, no CSS variables.
 * Colors are explicit hex strings so they render correctly inside React Flow.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { DeviceNode } from "@/lib/deviceTypes";

// ── Palette ───────────────────────────────────────────────────────────────────

const ACTIVE_STROKE = "#58a6ff";
const IDLE_STROKE   = "#58a6ff";
const BODY          = "#1c2128";
const SCREEN        = "#010409";
const MUTED         = "#484f58";
const ERROR_COLOR   = "#f85149";
const TEXT_MAIN     = "#e6edf3";
const TEXT_IP       = "#58a6ff";
const TEXT_MUTED    = "#8b949e";
const HANDLE_COLOR  = "#58a6ff";

// Show 4 handles (top/right/bottom/left) — both source and target
// so wires can be drawn in either direction from any side.
function handles() {
  const s: React.CSSProperties = {
    background: HANDLE_COLOR,
    border: "2px solid #0d1117",
    width: 10,
    height: 10,
    opacity: 0,  // hidden until hovered — CSS in globals makes them visible
    transition: "opacity 0.15s",
  };
  return (
    <>
      <Handle type="source" position={Position.Top}    style={s} id="t" />
      <Handle type="source" position={Position.Right}  style={s} id="r" />
      <Handle type="source" position={Position.Bottom} style={s} id="b" />
      <Handle type="source" position={Position.Left}   style={s} id="l" />
      <Handle type="target" position={Position.Top}    style={{ ...s, opacity: 0 }} id="tt" />
      <Handle type="target" position={Position.Right}  style={{ ...s, opacity: 0 }} id="tr" />
      <Handle type="target" position={Position.Bottom} style={{ ...s, opacity: 0 }} id="tb" />
      <Handle type="target" position={Position.Left}   style={{ ...s, opacity: 0 }} id="tl" />
    </>
  );
}

// ── PC icon ───────────────────────────────────────────────────────────────────

function PcSvg({ stroke, hasIp }: { stroke: string; hasIp: boolean }) {
  return (
    <svg width="44" height="38" viewBox="0 0 44 38" aria-hidden="true"
      style={{ display: "block", margin: "0 auto 4px" }}>
      <rect x="2" y="1" width="40" height="26" rx="2.5"
        fill={BODY} stroke={stroke} strokeWidth="1.5" />
      <rect x="5" y="4" width="34" height="20" rx="1" fill={SCREEN} />
      <text x="9" y="17" fill={hasIp ? "#3d5a80" : MUTED}
        fontSize="9" fontFamily="monospace" fontWeight="bold">&gt;_</text>
      <circle cx="36" cy="6" r="2.2"
        fill={hasIp ? "#3fb950" : ERROR_COLOR} />
      <rect x="18" y="27" width="8" height="4"
        fill={BODY} stroke={stroke} strokeWidth="1.2" />
      <rect x="11" y="31" width="22" height="4" rx="1.5"
        fill={BODY} stroke={stroke} strokeWidth="1.2" />
    </svg>
  );
}

// ── Laptop icon ───────────────────────────────────────────────────────────────

function LaptopSvg({ stroke, hasIp }: { stroke: string; hasIp: boolean }) {
  return (
    <svg width="44" height="36" viewBox="0 0 44 36" aria-hidden="true"
      style={{ display: "block", margin: "0 auto 4px" }}>
      {/* Lid */}
      <rect x="4" y="2" width="36" height="24" rx="2"
        fill={BODY} stroke={stroke} strokeWidth="1.5" />
      <rect x="7" y="5" width="30" height="18" rx="1" fill={SCREEN} />
      <text x="11" y="17" fill={hasIp ? "#3d5a80" : MUTED}
        fontSize="8" fontFamily="monospace">&gt;_</text>
      <circle cx="36" cy="7" r="2" fill={hasIp ? "#3fb950" : ERROR_COLOR} />
      {/* Base */}
      <rect x="1" y="26" width="42" height="6" rx="2"
        fill={BODY} stroke={stroke} strokeWidth="1.5" />
      {/* Hinge */}
      <rect x="16" y="24" width="12" height="4" rx="1"
        fill={BODY} stroke={stroke} strokeWidth="1" />
    </svg>
  );
}

// ── Server icon ───────────────────────────────────────────────────────────────

function ServerSvg({ stroke, hasIp }: { stroke: string; hasIp: boolean }) {
  return (
    <svg width="36" height="44" viewBox="0 0 36 44" aria-hidden="true"
      style={{ display: "block", margin: "0 auto 4px" }}>
      {/* Rack unit 1 */}
      <rect x="2" y="2" width="32" height="12" rx="2"
        fill={BODY} stroke={stroke} strokeWidth="1.5" />
      <circle cx="8" cy="8" r="2.5" fill={hasIp ? "#3fb950" : ERROR_COLOR} />
      <rect x="14" y="6" width="14" height="4" rx="1" fill={MUTED} opacity="0.5" />
      {/* Rack unit 2 */}
      <rect x="2" y="16" width="32" height="12" rx="2"
        fill={BODY} stroke={stroke} strokeWidth="1.5" />
      <circle cx="8" cy="22" r="2.5" fill="#58a6ff" opacity="0.8" />
      <rect x="14" y="20" width="14" height="4" rx="1" fill={MUTED} opacity="0.5" />
      {/* Rack unit 3 */}
      <rect x="2" y="30" width="32" height="12" rx="2"
        fill={BODY} stroke={stroke} strokeWidth="1.5" />
      <circle cx="8" cy="36" r="2.5" fill={MUTED} />
      <rect x="14" y="34" width="14" height="4" rx="1" fill={MUTED} opacity="0.3" />
    </svg>
  );
}

// ── Cisco Catalyst 2960 (L2 switch) icon ──────────────────────────────────────

function Switch2960Svg({ stroke, active }: { stroke: string; active: boolean }) {
  const portColors = ["#3fb950", "#3fb950", "#58a6ff", MUTED, MUTED, MUTED, MUTED, MUTED];
  return (
    <svg width="52" height="30" viewBox="0 0 52 30" aria-hidden="true"
      style={{ display: "block", margin: "0 auto 4px" }}>
      {/* Chassis */}
      <rect x="1" y="4" width="50" height="22" rx="3"
        fill={BODY} stroke={stroke} strokeWidth="1.5" />
      {/* Top bar */}
      <rect x="1" y="4" width="50" height="6" rx="3"
        fill={active ? "#1d3558" : "#161b22"} />
      {/* Model label */}
      <text x="4" y="10" fill={active ? ACTIVE_STROKE : "#484f58"}
        fontSize="6" fontFamily="ui-monospace,monospace" fontWeight="bold">
        2960
      </text>
      {/* Bidirectional arrow */}
      <line x1="6" y1="18" x2="13" y2="18"
        stroke={ACTIVE_STROKE} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M10 15 L13 18 L10 21"
        stroke={ACTIVE_STROKE} strokeWidth="1.5" fill="none"
        strokeLinecap="round" strokeLinejoin="round" />
      <line x1="46" y1="18" x2="39" y2="18"
        stroke={ACTIVE_STROKE} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M42 15 L39 18 L42 21"
        stroke={ACTIVE_STROKE} strokeWidth="1.5" fill="none"
        strokeLinecap="round" strokeLinejoin="round" />
      {/* Port LEDs */}
      {portColors.map((c, i) => (
        <rect key={i} x={17 + i * 4} y={21} width="3" height="4" rx="0.5"
          fill={c} />
      ))}
    </svg>
  );
}

// ── Cisco 2911 Router icon ────────────────────────────────────────────────────

function Router2911Svg({ stroke }: { stroke: string }) {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" aria-hidden="true"
      style={{ display: "block", margin: "0 auto 4px" }}>
      {/* Outer circle */}
      <circle cx="24" cy="24" r="21"
        fill={BODY} stroke={stroke} strokeWidth="1.5" />
      {/* Inner ring */}
      <circle cx="24" cy="24" r="13"
        fill="none" stroke={stroke} strokeWidth="0.75" opacity="0.35" />
      {/* Up */}
      <line x1="24" y1="6" x2="24" y2="14"
        stroke={ACTIVE_STROKE} strokeWidth="2" strokeLinecap="round" />
      <path d="M20 10 L24 6 L28 10"
        stroke={ACTIVE_STROKE} strokeWidth="2" fill="none"
        strokeLinecap="round" strokeLinejoin="round" />
      {/* Right */}
      <line x1="42" y1="24" x2="34" y2="24"
        stroke={ACTIVE_STROKE} strokeWidth="2" strokeLinecap="round" />
      <path d="M38 20 L42 24 L38 28"
        stroke={ACTIVE_STROKE} strokeWidth="2" fill="none"
        strokeLinecap="round" strokeLinejoin="round" />
      {/* Down */}
      <line x1="24" y1="42" x2="24" y2="34"
        stroke={ACTIVE_STROKE} strokeWidth="2" strokeLinecap="round" />
      <path d="M20 38 L24 42 L28 38"
        stroke={ACTIVE_STROKE} strokeWidth="2" fill="none"
        strokeLinecap="round" strokeLinejoin="round" />
      {/* Left */}
      <line x1="6" y1="24" x2="14" y2="24"
        stroke={ACTIVE_STROKE} strokeWidth="2" strokeLinecap="round" />
      <path d="M10 20 L6 24 L10 28"
        stroke={ACTIVE_STROKE} strokeWidth="2" fill="none"
        strokeLinecap="round" strokeLinejoin="round" />
      {/* "2911" label */}
      <text x="24" y="27" fill={ACTIVE_STROKE}
        fontSize="6" fontFamily="ui-monospace,monospace" fontWeight="bold"
        textAnchor="middle">2911</text>
    </svg>
  );
}

// ── Node card wrapper ─────────────────────────────────────────────────────────

function DeviceCard({
  selected,
  hasError,
  children,
}: {
  selected?: boolean;
  hasError?: boolean;
  children: React.ReactNode;
}) {
  const border = selected
    ? ACTIVE_STROKE
    : hasError
    ? ERROR_COLOR
    : "#30363d";

  return (
    <div style={{
      background: "#161b22",
      border: `2px solid ${border}`,
      borderRadius: 10,
      padding: "10px 14px",
      minWidth: 100,
      textAlign: "center",
      cursor: "pointer",
      userSelect: "none",
      boxShadow: selected
        ? `0 0 0 3px rgba(88,166,255,0.18), 0 4px 14px rgba(0,0,0,0.6)`
        : "0 2px 8px rgba(0,0,0,0.4)",
      transition: "border-color 0.15s, box-shadow 0.15s",
    }}>
      {children}
    </div>
  );
}

// ── PC ────────────────────────────────────────────────────────────────────────

export function PcNode({ data, selected }: NodeProps<DeviceNode>) {
  const hasIp = !!(data.ip && data.ip.includes("/"));
  const stroke = selected ? ACTIVE_STROKE : IDLE_STROKE;

  return (
    <DeviceCard selected={selected} hasError={!hasIp}>
      {handles()}
      <PcSvg stroke={stroke} hasIp={hasIp} />
      <div style={{ fontSize: 11, fontWeight: 700, color: TEXT_MAIN, fontFamily: "ui-monospace,monospace", marginBottom: 2 }}>
        {String(data.hostname || "PC")}
      </div>
      <div style={{ fontSize: 10, color: hasIp ? TEXT_IP : ERROR_COLOR, fontFamily: "ui-monospace,monospace" }}>
        {hasIp ? String(data.ip) : "no IP — dbl-click"}
      </div>
    </DeviceCard>
  );
}

// ── Laptop ────────────────────────────────────────────────────────────────────

export function LaptopNode({ data, selected }: NodeProps<DeviceNode>) {
  const hasIp = !!(data.ip && data.ip.includes("/"));
  const stroke = selected ? ACTIVE_STROKE : IDLE_STROKE;

  return (
    <DeviceCard selected={selected} hasError={!hasIp}>
      {handles()}
      <LaptopSvg stroke={stroke} hasIp={hasIp} />
      <div style={{ fontSize: 11, fontWeight: 700, color: TEXT_MAIN, fontFamily: "ui-monospace,monospace", marginBottom: 2 }}>
        {String(data.hostname || "Laptop")}
      </div>
      <div style={{ fontSize: 10, color: hasIp ? TEXT_IP : ERROR_COLOR, fontFamily: "ui-monospace,monospace" }}>
        {hasIp ? String(data.ip) : "no IP — dbl-click"}
      </div>
    </DeviceCard>
  );
}

// ── Server ────────────────────────────────────────────────────────────────────

export function ServerNode({ data, selected }: NodeProps<DeviceNode>) {
  const hasIp = !!(data.ip && data.ip.includes("/"));
  const stroke = selected ? ACTIVE_STROKE : IDLE_STROKE;

  return (
    <DeviceCard selected={selected} hasError={!hasIp}>
      {handles()}
      <ServerSvg stroke={stroke} hasIp={hasIp} />
      <div style={{ fontSize: 11, fontWeight: 700, color: TEXT_MAIN, fontFamily: "ui-monospace,monospace", marginBottom: 2 }}>
        {String(data.hostname || "Server")}
      </div>
      <div style={{ fontSize: 10, color: hasIp ? TEXT_IP : ERROR_COLOR, fontFamily: "ui-monospace,monospace" }}>
        {hasIp ? String(data.ip) : "no IP — dbl-click"}
      </div>
    </DeviceCard>
  );
}

// ── Catalyst 2960 Switch ──────────────────────────────────────────────────────

export function Switch2960Node({ data, selected }: NodeProps<DeviceNode>) {
  const stroke = selected ? ACTIVE_STROKE : IDLE_STROKE;

  return (
    <DeviceCard selected={selected}>
      {handles()}
      <Switch2960Svg stroke={stroke} active={!!selected} />
      <div style={{ fontSize: 11, fontWeight: 700, color: TEXT_MAIN, fontFamily: "ui-monospace,monospace", marginBottom: 2 }}>
        {String(data.hostname || "SW1")}
      </div>
      <div style={{ fontSize: 9, color: TEXT_MUTED, fontFamily: "ui-monospace,monospace" }}>
        Catalyst 2960
      </div>
    </DeviceCard>
  );
}

// ── 2911 Router ───────────────────────────────────────────────────────────────

export function Router2911Node({ data, selected }: NodeProps<DeviceNode>) {
  const stroke = selected ? ACTIVE_STROKE : IDLE_STROKE;

  return (
    <DeviceCard selected={selected}>
      {handles()}
      <Router2911Svg stroke={stroke} />
      <div style={{ fontSize: 11, fontWeight: 700, color: TEXT_MAIN, fontFamily: "ui-monospace,monospace", marginBottom: 2 }}>
        {String(data.hostname || "R1")}
      </div>
      <div style={{ fontSize: 9, color: "#f85149", fontFamily: "ui-monospace,monospace" }}>
        2911 — coming soon
      </div>
    </DeviceCard>
  );
}

// ── Node type registry ────────────────────────────────────────────────────────

export const nodeTypes = {
  "cisco-pc":     PcNode,
  "cisco-laptop": LaptopNode,
  "cisco-server": ServerNode,
  "cisco-2960":   Switch2960Node,
  "cisco-2911":   Router2911Node,
} as const;
