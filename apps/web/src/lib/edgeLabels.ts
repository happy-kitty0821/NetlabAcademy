/**
 * stampEdgeLabels
 * ───────────────
 * Re-assigns interface name labels on every edge based on current node
 * state. Called whenever nodes are added/removed so port numbers stay
 * consistent (Gi0/0, Gi0/1, …).
 *
 * Hosts always get "eth0". Switches get "Gi0/<n>" in edge-traversal order.
 */

import type { Edge } from "@xyflow/react";
import type { DeviceNode } from "./deviceTypes";

export function stampEdgeLabels(
  currentNodes: DeviceNode[],
  currentEdges: Edge[],
): Edge[] {
  const nodeMap  = new Map(currentNodes.map((n) => [n.id, n]));
  const counter  = new Map<string, number>();

  return currentEdges.map((edge) => {
    function getIface(nodeId: string): string {
      const node = nodeMap.get(nodeId);
      if (!node || node.data.model === "host") return "eth0";
      const c = counter.get(nodeId) ?? 0;
      counter.set(nodeId, c + 1);
      return `Gi0/${c}`;
    }
    const labelA = getIface(edge.source);
    const labelB = getIface(edge.target);
    return {
      ...edge,
      type: "lab",
      data: { ...edge.data, labelA, labelB, active: true },
    };
  });
}
