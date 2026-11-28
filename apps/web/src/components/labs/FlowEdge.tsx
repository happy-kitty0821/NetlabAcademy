"use client";

/**
 * FlowEdge — CML-style link between two devices.
 *
 * Links are straight lines between the centres of the two device tiles
 * (not between fixed ports), drawn from tile edge to tile edge.  Several
 * cables between the same two devices are spread apart so each stays
 * visible and clickable.  The interface at each end is labelled just
 * outside the device it belongs to.
 *
 * Colour follows the lab: grey while stopped, green while running, blue
 * when selected.
 */

import { useContext } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  useInternalNode,
  useStore,
  type Edge,
  type EdgeProps,
  type InternalNode,
} from "@xyflow/react";
import { LabRunningContext, NODE_TILE } from "./FlowNodes";

export interface EdgeData extends Record<string, unknown> {
  labelA?: string;
  labelB?: string;
  active?: boolean;
}

export type LabEdgeType = Edge<EdgeData>;

const PARALLEL_GAP = 12;   // px between cables joining the same two devices
const LABEL_GAP = 16;      // px from the tile edge to the interface label

/** Centre of a node's icon tile (the tile sits at the top, centred). */
function tileCentre(node: InternalNode): { x: number; y: number } {
  const { x, y } = node.internals.positionAbsolute;
  return { x: x + (node.measured.width ?? NODE_TILE) / 2, y: y + NODE_TILE / 2 };
}

/** Index of this edge among the cables joining the same pair, and how many. */
function useParallel(id: string, source: string, target: string): [number, number] {
  return useStore((s) => {
    const same = s.edges.filter((e) =>
      (e.source === source && e.target === target) || (e.source === target && e.target === source));
    return [Math.max(0, same.findIndex((e) => e.id === id)), same.length] as [number, number];
  }, (a, b) => a[0] === b[0] && a[1] === b[1]);
}

function PortLabel({ x, y, text, color }: { x: number; y: number; text: string; color: string }) {
  return (
    <div
      className="nodrag nopan"
      style={{
        position: "absolute",
        transform: `translate(-50%, -50%) translate(${x}px, ${y}px)`,
        pointerEvents: "none",
        fontSize: 10, lineHeight: "14px", fontWeight: 600,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        color, background: "rgba(255,255,255,0.92)",
        padding: "0 4px", borderRadius: 3, border: "1px solid #d0d7de",
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </div>
  );
}

export function LabEdge({ id, source, target, data, selected }: EdgeProps<LabEdgeType>) {
  const running = useContext(LabRunningContext);
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  const [index, count] = useParallel(id, source, target);
  if (!sourceNode || !targetNode) return null;

  // Keep the parallel offset stable whichever way round the cable was drawn.
  const flip = source > target ? -1 : 1;
  const a = tileCentre(sourceNode);
  const b = tileCentre(targetNode);
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const offset = (index - (count - 1) / 2) * PARALLEL_GAP * flip;
  const ox = -uy * offset;
  const oy = ux * offset;

  // Distance from a tile centre to its edge along this direction (square tile).
  const toEdge = (NODE_TILE / 2 + 2) / Math.max(Math.abs(ux), Math.abs(uy), 1e-6);
  const room = len - 2 * toEdge;
  if (room <= 0) return null;   // tiles overlap: nothing to draw

  const sx = a.x + ox + ux * toEdge;
  const sy = a.y + oy + uy * toEdge;
  const tx = b.x + ox - ux * toEdge;
  const ty = b.y + oy - uy * toEdge;
  const path = `M ${sx},${sy} L ${tx},${ty}`;

  // Labels sit just outside each tile; on a short link, at 25% / 75%.
  const along = room > 2 * (LABEL_GAP + 34) ? LABEL_GAP + 14 : room * 0.25;
  const labelA = data?.labelA ?? "";
  const labelB = data?.labelB ?? "";

  const color = selected ? "#0969da" : running ? "#2da44e" : "#6e7781";
  const labelColor = selected ? "#0969da" : "#1f2328";

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        interactionWidth={16}
        style={{
          stroke: color,
          strokeWidth: selected ? 3 : 2,
          strokeLinecap: "round",
          transition: "stroke 0.2s",
        }}
      />
      <EdgeLabelRenderer>
        {labelA && <PortLabel x={sx + ux * along} y={sy + uy * along} text={labelA} color={labelColor} />}
        {labelB && <PortLabel x={tx - ux * along} y={ty - uy * along} text={labelB} color={labelColor} />}
      </EdgeLabelRenderer>
    </>
  );
}

export const edgeTypes = {
  lab: LabEdge,
} as const;
