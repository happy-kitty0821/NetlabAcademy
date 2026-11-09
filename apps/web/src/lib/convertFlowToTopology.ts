/**
 * convertFlowToTopology
 * ─────────────────────
 * Converts a React Flow node/edge graph into a TopologyDocument suitable
 * for the simulation API.
 *
 * Rules:
 *  - Each Flow node → one TopologyNode (host or switch).
 *  - Hosts always get a single interface named "eth0".
 *  - Switches get one interface per connected edge, named "Gi0/0", "Gi0/1", …
 *  - mac_seed is set from the node's position in the array (deterministic).
 *  - Links are validated: both endpoints must exist.
 *  - Host IP is required; missing IP throws a ValidationError with the
 *    node's hostname so the UI can display it inline.
 */

import type { Node, Edge } from "@xyflow/react";
import type { TopologyDocument, TopologyNode, TopologyLink } from "./simulation-api";

// ── Node data shape ────────────────────────────────────────────────────────────

export interface DeviceNodeData extends Record<string, unknown> {
  hostname: string;
  model: "host" | "switch";
  ip?: string;          // CIDR string e.g. "192.168.1.1/24"  (hosts only)
  gateway?: string;
}

export type DeviceNode = Node<DeviceNodeData>;

// ── Validation error ──────────────────────────────────────────────────────────

export class TopologyValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TopologyValidationError";
  }
}

// ── Conversion ────────────────────────────────────────────────────────────────

export function convertFlowToTopology(
  nodes: DeviceNode[],
  edges: Edge[],
): TopologyDocument {
  if (nodes.length === 0) {
    throw new TopologyValidationError(
      "The topology has no devices. Add at least one PC and one Switch.",
    );
  }

  // Build a lookup: flow node id → edge count (for switch port naming)
  const edgeCountByNode = new Map<string, number>();
  for (const edge of edges) {
    edgeCountByNode.set(
      edge.source,
      (edgeCountByNode.get(edge.source) ?? 0) + 1,
    );
    edgeCountByNode.set(
      edge.target,
      (edgeCountByNode.get(edge.target) ?? 0) + 1,
    );
  }

  // Build interface name allocator per switch node
  const switchPortCounter = new Map<string, number>();

  // Convert nodes
  const topologyNodes: TopologyNode[] = nodes.map((node, idx) => {
    const data = node.data;
    const hostname = data.hostname || `${data.model}-${idx}`;

    if (data.model === "host") {
      if (!data.ip || !data.ip.includes("/")) {
        throw new TopologyValidationError(
          `PC "${hostname}" has no IP address configured. ` +
            `Double-click the device and set an IP (e.g. 192.168.1.1/24).`,
        );
      }

      return {
        id: node.id,
        model: "host",
        hostname,
        interfaces: [
          {
            name: "eth0",
            mac_seed: idx * 10,
            ip: data.ip,
            gateway: data.gateway || undefined,
          },
        ],
      };
    }

    // Switch — allocate one interface per connected edge
    const portCount = edgeCountByNode.get(node.id) ?? 0;
    const interfaces = Array.from({ length: Math.max(portCount, 2) }, (_, i) => ({
      name: `Gi0/${i}`,
      mac_seed: idx * 10 + i,
    }));

    return {
      id: node.id,
      model: "switch",
      hostname,
      interfaces,
    };
  });

  // Convert edges → links
  const nodeIds = new Set(nodes.map((n) => n.id));

  const topologyLinks: TopologyLink[] = edges.map((edge, idx) => {
    if (!nodeIds.has(edge.source)) {
      throw new TopologyValidationError(
        `Link ${idx + 1} references a device that no longer exists.`,
      );
    }
    if (!nodeIds.has(edge.target)) {
      throw new TopologyValidationError(
        `Link ${idx + 1} references a device that no longer exists.`,
      );
    }

    const srcNode = nodes.find((n) => n.id === edge.source)!;
    const dstNode = nodes.find((n) => n.id === edge.target)!;

    // Interface assignment:
    // Hosts always use eth0.
    // Switches get the next available Gi0/N port.
    function getIface(node: DeviceNode): string {
      if (node.data.model === "host") return "eth0";
      const count = switchPortCounter.get(node.id) ?? 0;
      switchPortCounter.set(node.id, count + 1);
      return `Gi0/${count}`;
    }

    return {
      id: edge.id,
      device_a: edge.source,
      interface_a: getIface(srcNode),
      device_b: edge.target,
      interface_b: getIface(dstNode),
    };
  });

  return { nodes: topologyNodes, links: topologyLinks };
}
