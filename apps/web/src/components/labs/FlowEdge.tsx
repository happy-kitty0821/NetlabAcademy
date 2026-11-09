"use client";

/**
 * FlowEdge — EVE-NG style cable with interface labels.
 *
 * Each cable renders as:
 *  - A thick colored line (green = active Ethernet, gray = unconnected)
 *  - A thin offset shadow for depth
 *  - Interface name label at each endpoint (e.g. "eth0", "Gi0/1")
 *    positioned 22% along the path from each device, above the cable
 *
 * The interface labels are placed using EdgeLabelRenderer so they are
 * rendered in HTML (not SVG), which means they can use proper fonts
 * and are not clipped by the SVG viewport.
 */

import {
  BaseEdge,
  EdgeLabelRenderer,
  getStraightPath,
  type Edge,
  type EdgeProps,
} from "@xyflow/react";

export interface EdgeData extends Record<string, unknown> {
  labelA?: string;
  labelB?: string;
  active?: boolean;
}

export type LabEdgeType = Edge<EdgeData>;

export function LabEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
  selected,
}: EdgeProps<LabEdgeType>) {
  const labelA = data?.labelA ?? "";
  const labelB = data?.labelB ?? "";
  const active = data?.active ?? true;

  const [edgePath] = getStraightPath({ sourceX, sourceY, targetX, targetY });

  // Colors
  const cableColor = selected
    ? "#58a6ff"
    : active
    ? "#3fb950"      // green = Ethernet up (EVE-NG default)
    : "#484f58";     // gray  = down

  const shadowColor = "rgba(0,0,0,0.5)";

  // Position label A at 20% along the line from source
  const labelAx = sourceX + (targetX - sourceX) * 0.2;
  const labelAy = sourceY + (targetY - sourceY) * 0.2;

  // Position label B at 20% from target (i.e. 80% from source)
  const labelBx = sourceX + (targetX - sourceX) * 0.8;
  const labelBy = sourceY + (targetY - sourceY) * 0.8;

  // Perpendicular offset direction (push labels away from the cable)
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  // Normal vector (rotate 90°)
  const nx = -dy / len;
  const ny = dx / len;
  const LABEL_OFFSET = 12;

  return (
    <>
      {/* Shadow (slightly offset, dark, behind) */}
      <BaseEdge
        id={`${id}-shadow`}
        path={edgePath}
        style={{
          stroke: shadowColor,
          strokeWidth: 5,
          strokeLinecap: "round",
          transform: "translate(1px, 1px)",
        }}
      />

      {/* Main cable */}
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: cableColor,
          strokeWidth: 3,
          strokeLinecap: "round",
          transition: "stroke 0.2s",
          filter: selected
            ? "drop-shadow(0 0 4px rgba(88,166,255,0.6))"
            : active
            ? "drop-shadow(0 0 2px rgba(63,185,80,0.25))"
            : "none",
        }}
      />

      {/* Interface labels via HTML overlay */}
      <EdgeLabelRenderer>
        {labelA && (
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelAx + nx * LABEL_OFFSET}px, ${labelAy + ny * LABEL_OFFSET}px)`,
              pointerEvents: "none",
            }}
            className="nodrag nopan"
          >
            <span style={{
              fontSize: 9,
              fontFamily: "ui-monospace, monospace",
              fontWeight: 600,
              color: selected ? "#58a6ff" : active ? "#3fb950" : "#8b949e",
              background: "#0d1117",
              padding: "1px 4px",
              borderRadius: 3,
              border: `1px solid ${selected ? "#1d3558" : "#21262d"}`,
              whiteSpace: "nowrap",
              letterSpacing: "0.03em",
            }}>
              {labelA}
            </span>
          </div>
        )}
        {labelB && (
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelBx + nx * LABEL_OFFSET}px, ${labelBy + ny * LABEL_OFFSET}px)`,
              pointerEvents: "none",
            }}
            className="nodrag nopan"
          >
            <span style={{
              fontSize: 9,
              fontFamily: "ui-monospace, monospace",
              fontWeight: 600,
              color: selected ? "#58a6ff" : active ? "#3fb950" : "#8b949e",
              background: "#0d1117",
              padding: "1px 4px",
              borderRadius: 3,
              border: `1px solid ${selected ? "#1d3558" : "#21262d"}`,
              whiteSpace: "nowrap",
              letterSpacing: "0.03em",
            }}>
              {labelB}
            </span>
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  );
}

export const edgeTypes = {
  lab: LabEdge,
} as const;
