"use client";

/**
 * FlowNodes — CML-style device nodes for the lab canvas.
 *
 * Each device is a flat icon tile (white glyph on a solid tile) with its
 * label underneath, like the Cisco Modeling Labs workbench:
 *
 *  - a state badge on the tile's corner: grey square = stopped, green
 *    check = started (the lab is running);
 *  - links attach to the centre of the tile (see FlowEdge), so a node has
 *    no visible ports.  Hovering a node shows a small connector on the
 *    tile's right edge: drag it onto another device to create a link.
 *    Dropping anywhere on the other device's tile connects to it.
 */

import { createContext, useContext } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { DeviceNode } from "@/lib/deviceTypes";

/** Size of the icon tile, in px.  FlowEdge uses it to find the tile centre. */
export const NODE_TILE = 52;

export type DeviceKind = "router" | "switch-l2" | "pc" | "laptop" | "server";

const TILE_COLOR: Record<DeviceKind, string> = {
  "router":    "#1f4f82",
  "switch-l2": "#1f4f82",
  "pc":        "#3e6a96",
  "laptop":    "#3e6a96",
  "server":    "#3e6a96",
};

const C = {
  label:     "#1f2328",
  sub:       "#57606a",
  warn:      "#bc4c00",
  selected:  "#0969da",
  started:   "#2da44e",
  stopped:   "#8c959f",
};

/** True while the lab simulation is running (drives the node state badge). */
export const LabRunningContext = createContext(false);

// ── Glyphs (white line art on the tile, 40×40 grid) ───────────────────────────

const STROKE = {
  stroke: "#ffffff", strokeWidth: 2.2, fill: "none",
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
};

function Arrow({ x1, y1, x2, y2 }: { x1: number; y1: number; x2: number; y2: number }) {
  // Line from (x1,y1) with an arrow head at (x2,y2).
  const a = Math.atan2(y2 - y1, x2 - x1);
  const h = 4.2;
  const p1 = [x2 - h * Math.cos(a - 0.6), y2 - h * Math.sin(a - 0.6)];
  const p2 = [x2 - h * Math.cos(a + 0.6), y2 - h * Math.sin(a + 0.6)];
  return (
    <>
      <line x1={x1} y1={y1} x2={x2} y2={y2} {...STROKE} />
      <polyline points={`${p1[0]},${p1[1]} ${x2},${y2} ${p2[0]},${p2[1]}`} {...STROKE} />
    </>
  );
}

function GlyphPaths({ kind }: { kind: DeviceKind }) {
  switch (kind) {
    case "router":
      // Ring with two arrows in and two arrows out.
      return (
        <>
          <circle cx="20" cy="20" r="13" {...STROKE} />
          <Arrow x1={20} y1={20} x2={27.5} y2={12.5} />
          <Arrow x1={20} y1={20} x2={12.5} y2={27.5} />
          <Arrow x1={12} y1={12} x2={17.5} y2={17.5} />
          <Arrow x1={28} y1={28} x2={22.5} y2={22.5} />
        </>
      );
    case "switch-l2":
      // Four lanes, alternating direction.
      return (
        <>
          <Arrow x1={9}  y1={11} x2={30} y2={11} />
          <Arrow x1={31} y1={17} x2={10} y2={17} />
          <Arrow x1={9}  y1={23} x2={30} y2={23} />
          <Arrow x1={31} y1={29} x2={10} y2={29} />
        </>
      );
    case "laptop":
      return (
        <>
          <rect x="10" y="10" width="20" height="14" rx="1.5" {...STROKE} />
          <path d="M6 29 L9 25 L31 25 L34 29 Z" {...STROKE} />
        </>
      );
    case "server":
      return (
        <>
          {[8, 17, 26].map((y) => (
            <g key={y}>
              <rect x="10" y={y} width="20" height="7" rx="1.5" {...STROKE} />
              <circle cx="14" cy={y + 3.5} r="0.9" fill="#ffffff" />
            </g>
          ))}
        </>
      );
    case "pc":
    default:
      return (
        <>
          <rect x="8" y="8" width="24" height="17" rx="1.5" {...STROKE} />
          <line x1="20" y1="25" x2="20" y2="30" {...STROKE} />
          <line x1="13" y1="31" x2="27" y2="31" {...STROKE} />
        </>
      );
  }
}

/** A device icon tile, also used by the device palette. */
export function DeviceTile({ kind, size = NODE_TILE }: { kind: DeviceKind; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" style={{ display: "block" }}>
      <rect x="0" y="0" width="40" height="40" rx="9" fill={TILE_COLOR[kind]} />
      <GlyphPaths kind={kind} />
    </svg>
  );
}

// ── State badge ───────────────────────────────────────────────────────────────

function StateBadge() {
  const running = useContext(LabRunningContext);
  return (
    <span
      title={running ? "Started" : "Stopped"}
      aria-label={running ? "Started" : "Stopped"}
      style={{
        position: "absolute", top: -6, right: -6, width: 16, height: 16, borderRadius: "50%",
        background: running ? C.started : C.stopped, border: "2px solid #ffffff",
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "background 0.2s",
      }}
    >
      <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
        {running
          ? <polyline points="1.2,4.2 3.2,6 6.8,1.8" fill="none" stroke="#fff" strokeWidth="1.6"
              strokeLinecap="round" strokeLinejoin="round" />
          : <rect x="1.8" y="1.8" width="4.4" height="4.4" rx="0.6" fill="#fff" />}
      </svg>
    </span>
  );
}

// ── Node ──────────────────────────────────────────────────────────────────────

const centreHandle: React.CSSProperties = {
  left: "50%", top: "50%", width: 1, height: 1, minWidth: 1, minHeight: 1,
  border: 0, background: "transparent", pointerEvents: "none",
  transform: "translate(-50%, -50%)",
};

function DeviceNodeView({ kind, label, sub, subTone, selected }: {
  kind: DeviceKind; label: string; sub?: string; subTone?: "warn"; selected?: boolean;
}) {
  return (
    <div className="lab-node" style={{
      display: "flex", flexDirection: "column", alignItems: "center", userSelect: "none",
    }}>
      <div className="lab-node-tile" style={{
        position: "relative", width: NODE_TILE, height: NODE_TILE, borderRadius: 12,
        boxShadow: selected
          ? `0 0 0 2px #ffffff, 0 0 0 4px ${C.selected}`
          : "0 1px 3px rgba(31,35,40,0.25)",
        transition: "box-shadow 0.15s",
      }}>
        <DeviceTile kind={kind} />
        <StateBadge />
        {/* Link anchor and drop target: the tile centre (never starts a drag). */}
        <Handle id="c" type="source" position={Position.Top}
          isConnectableStart={false} style={centreHandle} />
        {/* Hover connector: drag from here to another device to link them. */}
        <Handle id="link" type="source" position={Position.Right}
          className="lab-connector" title="Drag to another device to connect" />
      </div>
      <div style={{
        marginTop: 6, padding: "0 4px", borderRadius: 3, background: "rgba(255,255,255,0.85)",
        fontSize: 12, fontWeight: 600, lineHeight: "16px", color: C.label, whiteSpace: "nowrap",
      }}>
        {label}
      </div>
      {sub && (
        <div style={{
          padding: "0 4px", borderRadius: 3, background: "rgba(255,255,255,0.85)",
          fontSize: 10, lineHeight: "14px", whiteSpace: "nowrap",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          color: subTone === "warn" ? C.warn : C.sub,
        }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function hostSub(data: DeviceNode["data"]): { sub: string; subTone?: "warn" } {
  const ip = data.ip ? String(data.ip) : "";
  // An unaddressed PC is fine (it can be set from its console), so this is
  // a plain note, not a warning.
  return ip.includes("/") ? { sub: ip } : { sub: "no IP" };
}

// ── Exported node components ──────────────────────────────────────────────────

export function PcNode({ data, selected }: NodeProps<DeviceNode>) {
  return <DeviceNodeView kind="pc" label={String(data.hostname || "PC")} selected={selected} {...hostSub(data)} />;
}

export function LaptopNode({ data, selected }: NodeProps<DeviceNode>) {
  return <DeviceNodeView kind="laptop" label={String(data.hostname || "Laptop")} selected={selected} {...hostSub(data)} />;
}

export function ServerNode({ data, selected }: NodeProps<DeviceNode>) {
  return <DeviceNodeView kind="server" label={String(data.hostname || "Server")} selected={selected} {...hostSub(data)} />;
}

export function Switch2960Node({ data, selected }: NodeProps<DeviceNode>) {
  return <DeviceNodeView kind="switch-l2" label={String(data.hostname || "SW1")} selected={selected} />;
}

export function Router2911Node({ data, selected }: NodeProps<DeviceNode>) {
  return <DeviceNodeView kind="router" label={String(data.hostname || "R1")} selected={selected} />;
}

export const nodeTypes = {
  "cisco-pc":     PcNode,
  "cisco-laptop": LaptopNode,
  "cisco-server": ServerNode,
  "cisco-2960":   Switch2960Node,
  "cisco-2911":   Router2911Node,
} as const;
