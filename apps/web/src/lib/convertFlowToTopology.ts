/**
 * convertFlowToTopology
 * ─────────────────────
 * Converts a React Flow node/edge graph into a TopologyDocument suitable
 * for the simulation API.
 *
 * Also returns an ifaceMap (nodeId:edgeId → interfaceName) so the
 * topology editor can stamp interface labels onto the React Flow edges
 * for EVE-NG-style display.
 *
 * Design — single pre-assignment pass:
 *  1. Walk every edge and pre-assign interface names to both endpoints
 *     before building either the node list or the link list.
 *     This guarantees nodes and links are always consistent.
 *  2. Hosts always use "eth0".
 *  3. Switches use "Gi0/0", "Gi0/1", … assigned in edge-traversal order
 *     PER NODE, tracked by a per-node counter.
 *  4. Switches are given exactly as many interfaces as they have
 *     connected edges (minimum 2 for visual clarity).
 *  5. Validation: hosts require a CIDR IP, links must reference existing nodes.
 */

import type { Edge } from "@xyflow/react";
import type {
  TopologyDocument,
  TopologyNode,
  TopologyLink,
} from "./simulation-api";
import type { DeviceNode } from "./deviceTypes";

export type { DeviceNode };
export type { DeviceNodeData } from "./deviceTypes";

// ── Validation error ──────────────────────────────────────────────────────────

export class TopologyValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TopologyValidationError";
  }
}

// ── Result type ───────────────────────────────────────────────────────────────

export interface ConversionResult {
  topology: TopologyDocument;
  /**
   * Interface name map: `"${nodeId}:${edgeId}"` → interface name.
   * Use this to stamp labels onto React Flow edges after conversion.
   */
  ifaceMap: Map<string, string>;
}

// ── Conversion ────────────────────────────────────────────────────────────────

export function convertFlowToTopology(
  nodes: DeviceNode[],
  edges: Edge[],
): ConversionResult {
  if (nodes.length === 0) {
    throw new TopologyValidationError(
      "The topology has no devices. Add at least one PC and one Switch.",
    );
  }

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  // ── Phase 1: pre-assign interface names ────────────────────────────────────
  const ifaceAssignment = new Map<string, string>();
  const switchPortCounter = new Map<string, number>();

  for (const edge of edges) {
    if (!nodeMap.has(edge.source)) {
      throw new TopologyValidationError(
        `A link references device "${edge.source}" which does not exist.`,
      );
    }
    if (!nodeMap.has(edge.target)) {
      throw new TopologyValidationError(
        `A link references device "${edge.target}" which does not exist.`,
      );
    }

    function assignIface(nodeId: string): string {
      const node = nodeMap.get(nodeId)!;
      if (node.data.model === "host") return "eth0";
      const current = switchPortCounter.get(nodeId) ?? 0;
      switchPortCounter.set(nodeId, current + 1);
      return `Gi0/${current}`;
    }

    ifaceAssignment.set(`${edge.source}:${edge.id}`, assignIface(edge.source));
    ifaceAssignment.set(`${edge.target}:${edge.id}`, assignIface(edge.target));
  }

  // ── Phase 2: build TopologyNodes ───────────────────────────────────────────

  const topologyNodes: TopologyNode[] = nodes.map((node, idx) => {
    const data = node.data;
    const hostname = data.hostname || `${data.model}-${idx}`;

    if (data.model === "host") {
      if (!data.ip || !data.ip.trim().includes("/")) {
        throw new TopologyValidationError(
          `PC "${hostname}" has no IP address configured. ` +
            `Double-click the device and set an IP (e.g. 192.168.1.1/24).`,
        );
      }

      return {
        id: node.id,
        model: "host" as const,
        hostname,
        interfaces: [
          {
            name: "eth0",
            mac_seed: idx * 10,
            ip: data.ip.trim(),
            gateway: data.gateway?.trim() || undefined,
          },
        ],
      };
    }

    const portCount = switchPortCounter.get(node.id) ?? 0;
    const totalPorts = Math.max(portCount, 2);
    const interfaces = Array.from({ length: totalPorts }, (_, i) => ({
      name: `Gi0/${i}`,
      mac_seed: idx * 10 + i,
    }));

    return {
      id: node.id,
      model: "switch" as const,
      hostname,
      interfaces,
    };
  });

  // ── Phase 3: build TopologyLinks ───────────────────────────────────────────

  const topologyLinks: TopologyLink[] = edges.map((edge) => {
    const ifaceA = ifaceAssignment.get(`${edge.source}:${edge.id}`)!;
    const ifaceB = ifaceAssignment.get(`${edge.target}:${edge.id}`)!;

    return {
      id: edge.id,
      device_a: edge.source,
      interface_a: ifaceA,
      device_b: edge.target,
      interface_b: ifaceB,
    };
  });

  return {
    topology: { nodes: topologyNodes, links: topologyLinks },
    ifaceMap: ifaceAssignment,
  };
}
