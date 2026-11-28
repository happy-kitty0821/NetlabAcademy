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
import { DEFAULT_DEVICE_CATALOG, templatePortNames } from "./deviceTypes";
import { cablePorts, normalizeEdges, type CableData } from "./edgeLabels";

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
    const names = templatePortNames(t);
    const count = Math.max(portCount, model === "host" ? 1 : 2);
    return Array.from({ length: count }, (_, i) => {
      const name = names[i] ?? `${t.prefix}${t.startIndex + i}`;
      const iface: { name: string; mac_seed: number; ip?: string; gateway?: string } = {
        name,
        mac_seed: nodeIdx * 10 + i,
      };
      if (i === 0 && ip?.includes("/")) iface.ip = ip.trim();
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
    if (i === 0 && ip?.includes("/")) iface.ip = ip.trim();
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

  // ── Phase 1: ports chosen for each cable ────────────────────────────────────
  // Each edge records the interface used at each end (data.ifaceA on the
  // source, data.ifaceB on the target), chosen in the link dialog.  Older
  // edges are normalised first so they get real, free port names.
  const cabled = normalizeEdges(nodes, edges);
  const ifaceAssignment = new Map<string, string>();
  const switchPortCounter = new Map<string, number>();
  const seenPorts = new Map<string, string>(); // "node:port" -> edge id

  for (const edge of cabled) {
    for (const nodeId of [edge.source, edge.target]) {
      if (!nodeMap.has(nodeId)) {
        throw new TopologyValidationError(
          `A link references device "${nodeId}" which does not exist.`,
        );
      }
    }
    const data = (edge.data ?? {}) as CableData;
    const ends: [string, string | undefined][] = [[edge.source, data.ifaceA], [edge.target, data.ifaceB]];
    for (const [nodeId, port] of ends) {
      const host = nodeMap.get(nodeId)!.data.hostname || nodeId;
      if (!port) {
        throw new TopologyValidationError(`${host} has no free port left for one of its cables.`);
      }
      const key = `${nodeId}:${port}`;
      if (seenPorts.has(key)) {
        throw new TopologyValidationError(`${host} ${port} is used by two cables.`);
      }
      seenPorts.set(key, edge.id);
      ifaceAssignment.set(`${nodeId}:${edge.id}`, port);
    }
  }
  for (const node of nodes) {
    switchPortCounter.set(node.id, cablePorts(node).length);
  }

  // ── Phase 2: build TopologyNodes ───────────────────────────────────────────

  const topologyNodes: TopologyNode[] = nodes.map((node, idx) => {
    const data = node.data;
    const hostname = data.hostname || `${data.model}-${idx}`;

    if (data.model === "host") {
      // A PC without an address still starts (as in CML / Packet Tracer):
      // it comes up unaddressed and can be configured from its console
      // ("ipconfig <ip> <mask> [<gateway>]").
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

  const topologyLinks: TopologyLink[] = cabled.map((edge) => {
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
