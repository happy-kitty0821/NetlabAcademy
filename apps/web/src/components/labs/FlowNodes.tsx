"use client";

/**
 * Custom React Flow node types for the topology editor.
 *
 * Each node renders as a compact device card with the GNS3-style SVG
 * icon drawn inline (no foreignObject — that breaks in React Flow).
 * A selected/hovered state is shown via a border color change.
 *
 * Connection handles are placed on all four sides so links can be drawn
 * from any direction, matching Packet Tracer UX.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { DeviceNode } from "@/lib/convertFlowToTopology";

// ── Colours (no CSS vars — these must be hard-coded for SVG) ─────────────────

const C = {
  bg: "#161b22",
  border: "#30363d",
  borderActive: "#58a6ff",
  borderError: "#f85149",
  text: "#e6edf3",
  textMuted: "#8b949e",
  textIp: "#58a6ff",
  handle: "#58a6ff",
};

// ── PC Node ───────────────────────────────────────────────────────────────────

export function PcNode({ data, selected }: NodeProps<DeviceNode>) {
  const hasIp = !!data.ip;
  const borderColor = selected
    ? C.borderActive
    : !hasIp
    ? C.borderError
    : C.border;

  return (
    <div
      style={{
        background: C.bg,
        border: `2px solid ${borderColor}`,
        borderRadius: 10,
        padding: "10px 14px",
        minWidth: 110,
        textAlign: "center",
        cursor: "pointer",
        userSelect: "none",
        boxShadow: selected
          ? `0 0 0 3px rgba(88,166,255,0.2), 0 4px 12px rgba(0,0,0,0.5)`
          : "0 2px 8px rgba(0,0,0,0.4)",
        transition: "border-color 0.15s, box-shadow 0.15s",
      }}
    >
      {/* Connection handles — all 4 sides */}
      <Handle type="source" position={Position.Top} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="source" position={Position.Right} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="source" position={Position.Left} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="target" position={Position.Top} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="target" position={Position.Right} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="target" position={Position.Bottom} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="target" position={Position.Left} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />

      {/* PC icon — inline SVG paths */}
      <svg width="40" height="36" viewBox="0 0 40 36" aria-hidden="true" style={{ display: "block", margin: "0 auto 4px" }}>
        {/* Monitor body */}
        <rect x="2" y="1" width="36" height="24" rx="2.5" fill="#1c2128" stroke={borderColor} strokeWidth="1.5" />
        {/* Screen */}
        <rect x="5" y="4" width="30" height="18" rx="1" fill="#010409" />
        {/* Prompt */}
        <text x="9" y="16" fill={selected ? "#58a6ff" : "#3d5a80"} fontSize="8" fontFamily="monospace" fontWeight="bold">&gt;_</text>
        {/* Status dot */}
        {hasIp && <circle cx="32" cy="6" r="2" fill="#3fb950" />}
        {!hasIp && <circle cx="32" cy="6" r="2" fill="#f85149" />}
        {/* Neck */}
        <rect x="16" y="25" width="8" height="4" fill="#1c2128" stroke={borderColor} strokeWidth="1" />
        {/* Base */}
        <rect x="10" y="29" width="20" height="3" rx="1.5" fill="#1c2128" stroke={borderColor} strokeWidth="1" />
      </svg>

      {/* Hostname */}
      <div style={{ fontSize: 11, fontWeight: 700, color: C.text, fontFamily: "ui-monospace,monospace", marginBottom: 2 }}>
        {data.hostname || "PC"}
      </div>

      {/* IP address or hint */}
      {hasIp ? (
        <div style={{ fontSize: 10, color: C.textIp, fontFamily: "ui-monospace,monospace" }}>
          {data.ip}
        </div>
      ) : (
        <div style={{ fontSize: 10, color: "#f85149", fontFamily: "ui-monospace,monospace" }}>
          no IP — dbl-click
        </div>
      )}
    </div>
  );
}

// ── Switch Node ───────────────────────────────────────────────────────────────

export function SwitchNode({ data, selected }: NodeProps<DeviceNode>) {
  const borderColor = selected ? C.borderActive : C.border;

  return (
    <div
      style={{
        background: C.bg,
        border: `2px solid ${borderColor}`,
        borderRadius: 10,
        padding: "10px 16px",
        minWidth: 120,
        textAlign: "center",
        cursor: "pointer",
        userSelect: "none",
        boxShadow: selected
          ? `0 0 0 3px rgba(88,166,255,0.2), 0 4px 12px rgba(0,0,0,0.5)`
          : "0 2px 8px rgba(0,0,0,0.4)",
        transition: "border-color 0.15s, box-shadow 0.15s",
      }}
    >
      <Handle type="source" position={Position.Top} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="source" position={Position.Right} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="source" position={Position.Left} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="target" position={Position.Top} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="target" position={Position.Right} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="target" position={Position.Bottom} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />
      <Handle type="target" position={Position.Left} style={{ background: C.handle, border: "none", width: 8, height: 8 }} />

      {/* Switch icon */}
      <svg width="46" height="32" viewBox="0 0 46 32" aria-hidden="true" style={{ display: "block", margin: "0 auto 4px" }}>
        {/* Chassis */}
        <rect x="1" y="6" width="44" height="20" rx="3" fill="#1c2128" stroke={borderColor} strokeWidth="1.5" />
        {/* Top stripe */}
        <rect x="1" y="6" width="44" height="5" rx="3" fill={selected ? "#1d3558" : "#161b22"} />
        {/* Left arrow */}
        <line x1="7" y1="18" x2="14" y2="18" stroke={selected ? "#58a6ff" : "#58a6ff"} strokeWidth="1.5" strokeLinecap="round" />
        <path d="M11 15 L14 18 L11 21" stroke={selected ? "#58a6ff" : "#58a6ff"} strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        {/* Right arrow */}
        <line x1="39" y1="18" x2="32" y2="18" stroke="#58a6ff" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M35 15 L32 18 L35 21" stroke="#58a6ff" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        {/* Port LEDs */}
        {[18, 22, 26, 30, 34].map((x, i) => (
          <rect key={i} x={x} y={21} width="3" height="4" rx="0.5"
            fill={selected && i < 2 ? "#3fb950" : "#484f58"} />
        ))}
      </svg>

      {/* Hostname */}
      <div style={{ fontSize: 11, fontWeight: 700, color: C.text, fontFamily: "ui-monospace,monospace" }}>
        {data.hostname || "Switch"}
      </div>
      <div style={{ fontSize: 10, color: C.textMuted, fontFamily: "ui-monospace,monospace" }}>
        L2 Switch
      </div>
    </div>
  );
}

// ── Registry ──────────────────────────────────────────────────────────────────

export const nodeTypes = {
  pc: PcNode,
  switch: SwitchNode,
} as const;
