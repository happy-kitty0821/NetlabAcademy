"use client";

/**
 * FlowNodes — light-theme node icons for the topology canvas.
 *
 * Clean white cards with coloured icon strokes.
 * Handles are small blue dots always visible at the 4 cardinal points.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { DeviceNode } from "@/lib/deviceTypes";

// ── Light theme tokens ────────────────────────────────────────────────────────
const C = {
  card:       "#ffffff",
  cardBorder: "#d0d7de",
  selected:   "#0969da",
  iconBg:     "#f6f8fa",
  hostStroke: "#0969da",
  swStroke:   "#1a7f37",
  rtStroke:   "#9a6700",
  label:      "#1f2328",
  sub:        "#656d76",
  error:      "#d1242f",
  green:      "#1a7f37",
  screen:     "#0d1117",
  handle:     "#0969da",
  handleBg:   "#ffffff",
};

// ── Handles ───────────────────────────────────────────────────────────────────
function NodeHandles() {
  const s: React.CSSProperties = {
    width: 10, height: 10,
    background: C.handle,
    border: `2px solid ${C.handleBg}`,
    borderRadius: "50%",
    boxShadow: "0 0 0 1px #d0d7de",
  };
  return (
    <>
      <Handle type="source" position={Position.Top}    style={s}                    id="s-t" />
      <Handle type="source" position={Position.Right}  style={s}                    id="s-r" />
      <Handle type="source" position={Position.Bottom} style={s}                    id="s-b" />
      <Handle type="source" position={Position.Left}   style={s}                    id="s-l" />
      <Handle type="target" position={Position.Top}    style={{ ...s, opacity: 0 }} id="t-t" />
      <Handle type="target" position={Position.Right}  style={{ ...s, opacity: 0 }} id="t-r" />
      <Handle type="target" position={Position.Bottom} style={{ ...s, opacity: 0 }} id="t-b" />
      <Handle type="target" position={Position.Left}   style={{ ...s, opacity: 0 }} id="t-l" />
    </>
  );
}

// ── Card wrapper ──────────────────────────────────────────────────────────────
function Card({ selected, children }: { selected?: boolean; children: React.ReactNode }) {
  return (
    <div style={{
      background:   C.card,
      border:       `1.5px solid ${selected ? C.selected : C.cardBorder}`,
      borderRadius: 10,
      padding:      "10px 14px",
      minWidth:     90,
      textAlign:    "center",
      userSelect:   "none",
      boxShadow:    selected
        ? `0 0 0 3px rgba(9,105,218,0.15), 0 2px 8px rgba(0,0,0,0.1)`
        : "0 1px 4px rgba(0,0,0,0.08)",
      transition:   "border-color 0.15s, box-shadow 0.15s",
    }}>
      {children}
    </div>
  );
}

// ── SVG icons ─────────────────────────────────────────────────────────────────

function PcSvg({ s, hasIp }: { s: string; hasIp: boolean }) {
  return (
    <svg width="44" height="38" viewBox="0 0 44 38" aria-hidden="true" style={{ display: "block", margin: "0 auto 4px" }}>
      <rect x="2" y="1" width="40" height="26" rx="2.5" fill={C.iconBg} stroke={s} strokeWidth="1.5" />
      <rect x="5" y="4" width="34" height="20" rx="1" fill={C.screen} />
      <text x="10" y="17" fill={hasIp ? "#0969da" : "#656d76"} fontSize="8" fontFamily="monospace">&gt;_</text>
      <circle cx="37" cy="6" r="2.2" fill={hasIp ? C.green : C.error} />
      <rect x="18" y="27" width="8" height="4" fill={C.iconBg} stroke={s} strokeWidth="1.2" />
      <rect x="11" y="31" width="22" height="4" rx="1.5" fill={C.iconBg} stroke={s} strokeWidth="1.2" />
    </svg>
  );
}

function LaptopSvg({ s, hasIp }: { s: string; hasIp: boolean }) {
  return (
    <svg width="44" height="34" viewBox="0 0 44 36" aria-hidden="true" style={{ display: "block", margin: "0 auto 4px" }}>
      <rect x="4" y="2" width="36" height="24" rx="2" fill={C.iconBg} stroke={s} strokeWidth="1.5" />
      <rect x="7" y="5" width="30" height="18" rx="1" fill={C.screen} />
      <circle cx="36" cy="7" r="2" fill={hasIp ? C.green : C.error} />
      <rect x="1" y="26" width="42" height="6" rx="2" fill={C.iconBg} stroke={s} strokeWidth="1.5" />
    </svg>
  );
}

function ServerSvg({ s, hasIp }: { s: string; hasIp: boolean }) {
  return (
    <svg width="36" height="44" viewBox="0 0 36 44" aria-hidden="true" style={{ display: "block", margin: "0 auto 4px" }}>
      {[0, 1, 2].map((i) => (
        <g key={i}>
          <rect x="2" y={2 + i * 14} width="32" height="12" rx="2" fill={C.iconBg} stroke={s} strokeWidth="1.5" />
          <circle cx="8" cy={8 + i * 14} r="2.5"
            fill={i === 0 ? (hasIp ? C.green : C.error) : i === 1 ? C.hostStroke : C.sub} />
        </g>
      ))}
    </svg>
  );
}

function SwitchSvg({ s, active }: { s: string; active: boolean }) {
  return (
    <svg width="52" height="30" viewBox="0 0 52 30" aria-hidden="true" style={{ display: "block", margin: "0 auto 4px" }}>
      <rect x="1" y="4" width="50" height="22" rx="3" fill={C.iconBg} stroke={s} strokeWidth="1.5" />
      <rect x="1" y="4" width="50" height="7" rx="3" fill={active ? "#dafbe1" : C.iconBg} />
      <text x="4" y="10" fill={s} fontSize="6" fontFamily="monospace" fontWeight="bold">2960</text>
      <line x1="6" y1="19" x2="13" y2="19" stroke={s} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M10 16 L13 19 L10 22" stroke={s} strokeWidth="1.5" fill="none" strokeLinecap="round" />
      <line x1="46" y1="19" x2="39" y2="19" stroke={s} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M42 16 L39 19 L42 22" stroke={s} strokeWidth="1.5" fill="none" strokeLinecap="round" />
      {[0,1,2,3,4,5,6,7].map((i) => (
        <rect key={i} x={17 + i * 4} y={22} width="3" height="4" rx="0.5"
          fill={i < 2 ? C.green : i < 4 ? C.hostStroke : C.sub} opacity={i > 3 ? 0.3 : 1} />
      ))}
    </svg>
  );
}

function RouterSvg({ s }: { s: string }) {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" aria-hidden="true" style={{ display: "block", margin: "0 auto 4px" }}>
      <circle cx="24" cy="24" r="21" fill={C.iconBg} stroke={s} strokeWidth="1.5" />
      <circle cx="24" cy="24" r="13" fill="none" stroke={s} strokeWidth="0.75" opacity="0.3" />
      <line x1="24" y1="6" x2="24" y2="13"  stroke={s} strokeWidth="2" strokeLinecap="round" />
      <path d="M20 10 L24 6 L28 10"           stroke={s} strokeWidth="2" fill="none" strokeLinecap="round" />
      <line x1="42" y1="24" x2="35" y2="24"  stroke={s} strokeWidth="2" strokeLinecap="round" />
      <path d="M38 20 L42 24 L38 28"          stroke={s} strokeWidth="2" fill="none" strokeLinecap="round" />
      <line x1="6"  y1="24" x2="13" y2="24"  stroke={s} strokeWidth="2" strokeLinecap="round" />
      <path d="M10 20 L6 24 L10 28"           stroke={s} strokeWidth="2" fill="none" strokeLinecap="round" />
      <line x1="24" y1="42" x2="24" y2="35"  stroke={s} strokeWidth="2" strokeLinecap="round" />
      <path d="M20 38 L24 42 L28 38"          stroke={s} strokeWidth="2" fill="none" strokeLinecap="round" />
      <text x="24" y="27" fill={s} fontSize="6" fontFamily="monospace" fontWeight="bold" textAnchor="middle">2911</text>
    </svg>
  );
}

// ── Node label row ────────────────────────────────────────────────────────────
function NodeLabel({ main, sub, subColor }: { main: string; sub?: string; subColor?: string }) {
  return (
    <>
      <div style={{ fontSize: 11, fontWeight: 700, color: C.label, fontFamily: "ui-monospace,monospace" }}>{main}</div>
      {sub && <div style={{ fontSize: 9, color: subColor ?? C.sub, fontFamily: "ui-monospace,monospace", marginTop: 1 }}>{sub}</div>}
    </>
  );
}

// ── Exported node components ──────────────────────────────────────────────────

export function PcNode({ data, selected }: NodeProps<DeviceNode>) {
  const hasIp = !!(data.ip && String(data.ip).includes("/"));
  return (
    <Card selected={selected}>
      <NodeHandles />
      <PcSvg s={selected ? C.selected : C.hostStroke} hasIp={hasIp} />
      <NodeLabel main={String(data.hostname || "PC")}
        sub={hasIp ? String(data.ip) : "no IP — dbl-click"}
        subColor={hasIp ? C.hostStroke : C.error} />
    </Card>
  );
}

export function LaptopNode({ data, selected }: NodeProps<DeviceNode>) {
  const hasIp = !!(data.ip && String(data.ip).includes("/"));
  return (
    <Card selected={selected}>
      <NodeHandles />
      <LaptopSvg s={selected ? C.selected : C.hostStroke} hasIp={hasIp} />
      <NodeLabel main={String(data.hostname || "Laptop")}
        sub={hasIp ? String(data.ip) : "no IP — dbl-click"}
        subColor={hasIp ? C.hostStroke : C.error} />
    </Card>
  );
}

export function ServerNode({ data, selected }: NodeProps<DeviceNode>) {
  const hasIp = !!(data.ip && String(data.ip).includes("/"));
  return (
    <Card selected={selected}>
      <NodeHandles />
      <ServerSvg s={selected ? C.selected : C.hostStroke} hasIp={hasIp} />
      <NodeLabel main={String(data.hostname || "Server")}
        sub={hasIp ? String(data.ip) : "no IP — dbl-click"}
        subColor={hasIp ? C.hostStroke : C.error} />
    </Card>
  );
}

export function Switch2960Node({ data, selected }: NodeProps<DeviceNode>) {
  return (
    <Card selected={selected}>
      <NodeHandles />
      <SwitchSvg s={selected ? C.selected : C.swStroke} active={!!selected} />
      <NodeLabel main={String(data.hostname || "SW1")} sub="Catalyst 2960" subColor={C.swStroke} />
    </Card>
  );
}

export function Router2911Node({ data, selected }: NodeProps<DeviceNode>) {
  return (
    <Card selected={selected}>
      <NodeHandles />
      <RouterSvg s={selected ? C.selected : C.rtStroke} />
      <NodeLabel main={String(data.hostname || "R1")} sub="ISR 2911" subColor={C.rtStroke} />
    </Card>
  );
}

export const nodeTypes = {
  "cisco-pc":     PcNode,
  "cisco-laptop": LaptopNode,
  "cisco-server": ServerNode,
  "cisco-2960":   Switch2960Node,
  "cisco-2911":   Router2911Node,
} as const;
