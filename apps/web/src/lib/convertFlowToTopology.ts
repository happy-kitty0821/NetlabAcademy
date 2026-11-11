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
 *  2. Hosts use the first port from their interfaceTemplate (eth0) or
 *     fall back to "eth0".
 *  3. Switches/routers use port names from their interfaceTemplate,
 *     assigned in edge-traversal order per node using a per-node counter.
 *     If no template is known, falls back to "Gi0/<n>".
 *  4. Switches are given exactly as many interfaces as they have
 *     connected edges (minimum 2 for visual clarity), all from the
 *     template when present.
 *  5. Validation: hosts require a CIDR IP, links must reference existing nodes.
 */

import type { Edge } from "@xyflow/react";
import type {
  TopologyDocument,
  TopologyNode,
  TopologyLink,
} from "./simulation-api";
import type { DeviceNode } from "./deviceTypes";
import { DEFAULT_DEVICE_CATALOG } from "./deviceTypes";

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

// ── Helper: resolve interface name for a node's n-th port ─────────────────────

function resolvePortName(
  catalogId: string | undefined,
  model: "host" | "switch" | "router",
  portIndex: number,
): string {
  const entry = catalogId
    ? DEFAULT_DEVICE_CATALOG.find((e) => e.id === catalogId)
    : undefined;

  if (entry?.interfaceTemplate) {
    const t = entry.interfaceTemplate;
    return `${t.prefix}${t.startIndex + portIndex}`;
  }

  // Fallback when no catalog entry / template is present.
  if (model === "host") return "eth0";
  return `Gi0/${portIndex}`;
}

// ── Helper: generate the full interface list for a node from its template ─────

function generateInterfacesFromTemplate(
  node: DeviceNode,
  nodeIdx: number,
  portCount: number,
): Array<{ name: string; mac_seed: number; ip?: string; gateway?: string }> {
  const { catalogId, model, ip, gateway } = node.data;
  const entry = catalogId
    ? DEFAULT_DEVICE_CATALOG.find((e) => e.id === catalogId)
    : undefined;

  if (entry?.interfaceTemplate) {
    const t = entry.interfaceTemplate;
    const count = Math.max(portCount, model === "host" ? 1 : 2);
    return Array.from({ length: count }, (_, i) => {
      const name = `${t.prefix}${t.startIndex + i}`;
      const iface: { name: string; mac_seed: number; ip?: string; gateway?: string } = {
        name,
        mac_seed: nodeIdx * 10 + i,
      };
      if (i === 0 && ip) iface.ip = ip.trim();
      if (i === 0 && gateway) iface.gateway = gateway.trim();
      return iface;
    });
  }

  // Fallback: generate generic names.
  const count = Math.max(portCount, model === "host" ? 1 : 2);
  return Array.from({ length: count }, (_, i) => {
    const name = model === "host" ? "eth0" : `Gi0/${i}`;
    const iface: { name: string; mac_seed: number; ip?: string; gateway?: string } = {
      name,
      mac_seed: nodeIdx * 10 + i,
    };
    if (i === 0 && ip) iface.ip = ip.trim();
    if (i === 0 && gateway) iface.gateway = gateway.trim();
    return iface;
  });
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
      if (node.data.model === "host") {
        // Hosts always use their first port (eth0 or template port 0).
        return resolvePortName(node.data.catalogId, "host", 0);
      }
      const current = switchPortCounter.get(nodeId) ?? 0;
      switchPortCounter.set(nodeId, current + 1);
      return resolvePortName(node.data.catalogId, node.data.model, current);
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

      const interfaces = generateInterfacesFromTemplate(node, idx, 1);
      return {
        id: node.id,
        model: "host" as const,
        hostname,
        catalogId: data.catalogId,
        interfaces,
      };
    }

    const portCount = switchPortCounter.get(node.id) ?? 0;
    const interfaces = generateInterfacesFromTemplate(node, idx, portCount);

    if (data.model === "router") {
      return {
        id: node.id,
        model: "router" as const,
        hostname,
        catalogId: data.catalogId,
        interfaces,
      };
    }

    return {
      id: node.id,
      model: "switch" as const,
      hostname,
      catalogId: data.catalogId,
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
