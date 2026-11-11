"use client";

/**
 * FlowNodes — Cisco CML-style node icons for the topology canvas.
 *
 * Design principles (matching CML 2.x exactly):
 *  - No card/box wrapper. Just an SVG icon + hostname label beneath it.
 *  - Transparent background — the dot-grid canvas shows through.
 *  - Four connection handles (N/S/E/W) always visible as small circles.
 *  - Selected state: cyan glow ring around the icon.
 *  - Dragging works because there is no opaque div stealing pointer events.
 *
 * CML color palette:
 *  Background:  #1a1a2e (dark navy canvas)
 *  Icon fill:   #0f3460 / #16213e
 *  Icon stroke: #e94560 (red-orange for routers), #00b4d8 (cyan for switches),
 *               #48cae4 (light cyan for hosts)
 *  Label:       #e0e0e0
 *  Selected:    #00b4d8 ring
 *  Handle:      #00b4d8 dot
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { DeviceNode } from "@/lib/deviceTypes";

// ── CML colour tokens ─────────────────────────────────────────────────────────
const C = {
  canvas:     "#1a1a2e",
  iconFill:   "#0f3460",
  iconDark:   "#16213e",
  hostStroke: "#48cae4",   // hosts — light cyan
  swStroke:   "#00b4d8",   // switches — cyan
  rtStroke:   "#e94560",   // routers — red-orange
  selected:   "#00b4d8",
  label:      "#cdd6f4",
  labelMuted: "#7c7f93",
  handle:     "#00b4d8",
  handleBg:   "#1a1a2e",
  error:      "#e94560",
  green:      "#a6e3a1",
  screen:     "#020510",
};

// ── Handle set — always visible, positioned outside the icon ─────────────────
// Using Position enum values and explicit pixel offsets so they sit cleanly
// on the edge of the icon bounds regardless of icon size.

function NodeHandles() {
  const base: React.CSSProperties = {
    width:        10,
    height:       10,
    background:   C.handle,
    border:       `2px solid ${C.handleBg}`,
    borderRadius: "50%",
  };
  return (
    <>
      <Handle type="source" position={Position.Top}    style={base}                    id="s-t" />
      <Handle type="source" position={Position.Right}  style={base}                    id="s-r" />
      <Handle type="source" position={Position.Bottom} style={base}                    id="s-b" />
      <Handle type="source" position={Position.Left}   style={base}                    id="s-l" />
      <Handle type="target" position={Position.Top}    style={{ ...base, opacity: 0 }} id="t-t" />
      <Handle type="target" position={Position.Right}  style={{ ...base, opacity: 0 }} id="t-r" />
      <Handle type="target" position={Position.Bottom} style={{ ...base, opacity: 0 }} id="t-b" />
      <Handle type="target" position={Position.Left}   style={{ ...base, opacity: 0 }} id="t-l" />
    </>
  );
}

// ── Shared node wrapper ───────────────────────────────────────────────────────
// No background, no border — transparent so the canvas shows through.
// The selection ring is painted directly in SVG.

function CMLNode({
  selected, icon, label, sublabel, sublabelColor,
}: {
  selected?:      boolean;
  icon:           React.ReactNode;
  label:          string;
  sublabel?:      string;
  sublabelColor?: string;
}) {
  return (
    <div style={{
      display:        "flex",
      flexDirection:  "column",
      alignItems:     "center",
      gap:            4,
      background:     "transparent",
      border:         "none",
      padding:        0,
      userSelect:     "none",
      cursor:         "default",
      filter:         selected ? `drop-shadow(0 0 8px ${C.selected})` : "none",
      transition:     "filter 0.15s",
    }}>
      <NodeHandles />
      {icon}
      <div style={{ fontSize: 11, fontWeight: 700, color: C.label,
        fontFamily: "ui-monospace,monospace", whiteSpace: "nowrap",
        marginTop: 2, textShadow: "0 1px 3px rgba(0,0,0,0.9)" }}>
        {label}
      </div>
      {sublabel && (
        <div style={{ fontSize: 9, color: sublabelColor ?? C.labelMuted,
          fontFamily: "ui-monospace,monospace", marginTop: -2,
          textShadow: "0 1px 2px rgba(0,0,0,0.9)" }}>
          {sublabel}
        </div>
      )}
    </div>
  );
}

// ── PC / Laptop / Server icons ────────────────────────────────────────────────
// CML uses flat geometric icons — no gradients, clean shapes.

function PcIcon({ sel, hasIp }: { sel: boolean; hasIp: boolean }) {
  const s = sel ? C.selected : C.hostStroke;
  return (
    <svg width="52" height="46" viewBox="0 0 52 46" aria-hidden="true">
      {/* Monitor */}
      <rect x="2" y="1" width="48" height="32" rx="3" fill={C.iconFill} stroke={s} strokeWidth="1.8" />
      <rect x="6" y="5" width="40" height="24" rx="1.5" fill={C.screen} />
      {/* Cursor blink */}
      <rect x="10" y="20" width="6" height="2" rx="1" fill={hasIp ? C.swStroke : C.labelMuted} opacity="0.8" />
      {/* Status LED */}
      <circle cx="45" cy="4" r="2.5" fill={hasIp ? C.green : C.error} />
      {/* Stand */}
      <rect x="22" y="33" width="8" height="5" fill={C.iconFill} stroke={s} strokeWidth="1.2" />
      <rect x="15" y="38" width="22" height="5" rx="2" fill={C.iconFill} stroke={s} strokeWidth="1.2" />
    </svg>
  );
}

function LaptopIcon({ sel, hasIp }: { sel: boolean; hasIp: boolean }) {
  const s = sel ? C.selected : C.hostStroke;
  return (
    <svg width="54" height="40" viewBox="0 0 54 40" aria-hidden="true">
      {/* Lid */}
      <rect x="4" y="1" width="46" height="29" rx="3" fill={C.iconFill} stroke={s} strokeWidth="1.8" />
      <rect x="8" y="5" width="38" height="21" rx="1.5" fill={C.screen} />
      <circle cx="49" cy="4" r="2.5" fill={hasIp ? C.green : C.error} />
      {/* Keyboard base */}
      <rect x="1" y="30" width="52" height="8" rx="2.5" fill={C.iconFill} stroke={s} strokeWidth="1.8" />
      <rect x="20" y="28" width="14" height="4" rx="1" fill={C.iconDark} />
    </svg>
  );
}

function ServerIcon({ sel, hasIp }: { sel: boolean; hasIp: boolean }) {
  const s = sel ? C.selected : C.hostStroke;
  return (
    <svg width="44" height="52" viewBox="0 0 44 52" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <g key={i}>
          <rect x="2" y={2 + i * 17} width="40" height="14" rx="2.5"
            fill={C.iconFill} stroke={s} strokeWidth="1.8" />
          <circle cx="8" cy={9 + i * 17} r="2.5"
            fill={i === 0 ? (hasIp ? C.green : C.error) : i === 1 ? C.swStroke : C.labelMuted} />
          <rect x="14" cy={7 + i * 17} width="20" height="4" rx="1"
            fill={C.iconDark} opacity="0.8" />
        </g>
      ))}
    </svg>
  );
}

function SwitchIcon({ sel }: { sel: boolean }) {
  const s = sel ? C.selected : C.swStroke;
  const portLit = [true, true, true, false, false, false, false, false];
  return (
    <svg width="64" height="36" viewBox="0 0 64 36" aria-hidden="true">
      {/* Chassis */}
      <rect x="1" y="4" width="62" height="28" rx="4" fill={C.iconFill} stroke={s} strokeWidth="1.8" />
      {/* Front panel band */}
      <rect x="1" y="4" width="62" height="9" rx="4" fill={C.iconDark} />
      {/* Model text */}
      <text x="5" y="11.5" fill={s} fontSize="6.5" fontFamily="ui-monospace,monospace" fontWeight="bold">2960</text>
      {/* Bidirectional arrows */}
      <line x1="5" y1="22" x2="14" y2="22" stroke={s} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M11 19 L14 22 L11 25" stroke={s} strokeWidth="1.5" fill="none" strokeLinecap="round" />
      <line x1="59" y1="22" x2="50" y2="22" stroke={s} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M53 19 L50 22 L53 25" stroke={s} strokeWidth="1.5" fill="none" strokeLinecap="round" />
      {/* Port LEDs */}
      {portLit.map((lit, i) => (
        <rect key={i} x={19 + i * 5} y={28} width="4" height="4" rx="0.8"
          fill={lit ? C.green : C.labelMuted} opacity={lit ? 1 : 0.4} />
      ))}
    </svg>
  );
}

function RouterIcon({ sel }: { sel: boolean }) {
  const s = sel ? C.selected : C.rtStroke;
  return (
    <svg width="52" height="52" viewBox="0 0 52 52" aria-hidden="true">
      {/* Outer ring */}
      <circle cx="26" cy="26" r="23" fill={C.iconFill} stroke={s} strokeWidth="1.8" />
      {/* Inner ring */}
      <circle cx="26" cy="26" r="14" fill="none" stroke={s} strokeWidth="0.8" opacity="0.3" />
      {/* 4 directional arrows */}
      {/* Up */}
      <line x1="26" y1="7" x2="26" y2="14" stroke={s} strokeWidth="2" strokeLinecap="round" />
      <path d="M22 11 L26 7 L30 11" stroke={s} strokeWidth="2" fill="none" strokeLinecap="round" />
      {/* Right */}
      <line x1="45" y1="26" x2="38" y2="26" stroke={s} strokeWidth="2" strokeLinecap="round" />
      <path d="M41 22 L45 26 L41 30" stroke={s} strokeWidth="2" fill="none" strokeLinecap="round" />
      {/* Down */}
      <line x1="26" y1="45" x2="26" y2="38" stroke={s} strokeWidth="2" strokeLinecap="round" />
      <path d="M22 41 L26 45 L30 41" stroke={s} strokeWidth="2" fill="none" strokeLinecap="round" />
      {/* Left */}
      <line x1="7" y1="26" x2="14" y2="26" stroke={s} strokeWidth="2" strokeLinecap="round" />
      <path d="M11 22 L7 26 L11 30" stroke={s} strokeWidth="2" fill="none" strokeLinecap="round" />
      {/* Model */}
      <text x="26" y="29" fill={s} fontSize="6" fontFamily="ui-monospace,monospace"
        fontWeight="bold" textAnchor="middle">2911</text>
    </svg>
  );
}

// ── Exported node components ──────────────────────────────────────────────────

export function PcNode({ data, selected }: NodeProps<DeviceNode>) {
  const hasIp = !!(data.ip && String(data.ip).includes("/"));
  return (
    <CMLNode
      selected={selected}
      icon={<PcIcon sel={!!selected} hasIp={hasIp} />}
      label={String(data.hostname || "PC")}
      sublabel={hasIp ? String(data.ip) : "no IP"}
      sublabelColor={hasIp ? C.swStroke : C.error}
    />
  );
}

export function LaptopNode({ data, selected }: NodeProps<DeviceNode>) {
  const hasIp = !!(data.ip && String(data.ip).includes("/"));
  return (
    <CMLNode
      selected={selected}
      icon={<LaptopIcon sel={!!selected} hasIp={hasIp} />}
      label={String(data.hostname || "Laptop")}
      sublabel={hasIp ? String(data.ip) : "no IP"}
      sublabelColor={hasIp ? C.swStroke : C.error}
    />
  );
}

export function ServerNode({ data, selected }: NodeProps<DeviceNode>) {
  const hasIp = !!(data.ip && String(data.ip).includes("/"));
  return (
    <CMLNode
      selected={selected}
      icon={<ServerIcon sel={!!selected} hasIp={hasIp} />}
      label={String(data.hostname || "Server")}
      sublabel={hasIp ? String(data.ip) : "no IP"}
      sublabelColor={hasIp ? C.swStroke : C.error}
    />
  );
}

export function Switch2960Node({ data, selected }: NodeProps<DeviceNode>) {
  return (
    <CMLNode
      selected={selected}
      icon={<SwitchIcon sel={!!selected} />}
      label={String(data.hostname || "SW1")}
      sublabel="Catalyst 2960"
      sublabelColor={C.swStroke}
    />
  );
}

export function Router2911Node({ data, selected }: NodeProps<DeviceNode>) {
  return (
    <CMLNode
      selected={selected}
      icon={<RouterIcon sel={!!selected} />}
      label={String(data.hostname || "R1")}
      sublabel="ISR 2911"
      sublabelColor={C.rtStroke}
    />
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
