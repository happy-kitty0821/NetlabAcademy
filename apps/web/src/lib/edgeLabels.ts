/**
 * Cable ports
 * ───────────
 * Every cable (React Flow edge) records the exact interface used at each
 * end: `data.ifaceA` on the source device, `data.ifaceB` on the target.
 * The user picks them in the link dialog when connecting (CML-style); the
 * labels drawn on the cable are those names, and the simulator receives
 * exactly the same ones.
 *
 * Interface names come from the device catalog (deviceTypes.ts), e.g. a
 * 2960 has Fa0/1-Fa0/24 and Gi0/1-Gi0/2; a PC has eth0.
 */

import type { Edge } from "@xyflow/react";
import { DEFAULT_DEVICE_CATALOG, templatePortNames, type DeviceNode } from "./deviceTypes";

export interface CableData extends Record<string, unknown> {
  ifaceA?: string;   // port on edge.source
  ifaceB?: string;   // port on edge.target
  labelA?: string;
  labelB?: string;
  active?: boolean;
}

/** All cable ports a device offers, in hardware order. */
export function cablePorts(node: DeviceNode | undefined): string[] {
  if (!node) return [];
  const entry = DEFAULT_DEVICE_CATALOG.find((e) => e.id === node.data.catalogId);
  if (entry?.interfaceTemplate) return templatePortNames(entry.interfaceTemplate);
  return node.data.model === "host" ? ["eth0"] : ["Gi0/0", "Gi0/1", "Gi0/2"];
}

/** The port an edge uses on a given device (or undefined). */
export function portOn(edge: Edge, nodeId: string): string | undefined {
  const d = (edge.data ?? {}) as CableData;
  if (edge.source === nodeId) return d.ifaceA;
  if (edge.target === nodeId) return d.ifaceB;
  return undefined;
}

/** Ports of *nodeId* already cabled, mapped to "peer-hostname port". */
export function usedPorts(
  nodeId: string, nodes: DeviceNode[], edges: Edge[], ignoreEdgeId?: string,
): Map<string, string> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const used = new Map<string, string>();
  for (const e of edges) {
    if (e.id === ignoreEdgeId) continue;
    const mine = portOn(e, nodeId);
    if (!mine) continue;
    const peerId = e.source === nodeId ? e.target : e.source;
    const peerPort = portOn(e, peerId) ?? "?";
    used.set(mine, `${byId.get(peerId)?.data.hostname ?? peerId} ${peerPort}`);
  }
  return used;
}

/** First port of a device not already in use, or undefined if all taken. */
export function firstFreePort(
  nodeId: string, nodes: DeviceNode[], edges: Edge[], ignoreEdgeId?: string,
): string | undefined {
  const node = nodes.find((n) => n.id === nodeId);
  const used = usedPorts(nodeId, nodes, edges, ignoreEdgeId);
  return cablePorts(node).find((p) => !used.has(p));
}

/**
 * Make every edge carry valid ports and matching labels.
 *
 * Edges from older saved labs (no `ifaceA`/`ifaceB`, or names that the
 * device does not have, such as the old "Gi0/0" on a 2960) are given the
 * device's first free real ports.  Returns the same array when nothing
 * changes, so it is safe to call from effects.
 */
export function normalizeEdges(nodes: DeviceNode[], edges: Edge[]): Edge[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  let changed = false;
  const out: Edge[] = [];
  for (const edge of edges) {
    // Devices not known yet (e.g. a canvas being restored in the same
    // render): leave the cable exactly as stored rather than reassigning.
    if (!byId.has(edge.source) || !byId.has(edge.target)) {
      out.push(edge);
      continue;
    }
    const d = (edge.data ?? {}) as CableData;
    const sourcePorts = cablePorts(byId.get(edge.source));
    const targetPorts = cablePorts(byId.get(edge.target));
    const usedSoFar = (nodeId: string) => new Set(out.map((e) => portOn(e, nodeId)).filter(Boolean));
    let ifaceA = d.ifaceA;
    let ifaceB = d.ifaceB;
    if (!ifaceA || !sourcePorts.includes(ifaceA) || usedSoFar(edge.source).has(ifaceA)) {
      const used = usedSoFar(edge.source);
      ifaceA = sourcePorts.find((p) => !used.has(p));
    }
    if (!ifaceB || !targetPorts.includes(ifaceB) || usedSoFar(edge.target).has(ifaceB)) {
      const used = usedSoFar(edge.target);
      ifaceB = targetPorts.find((p) => !used.has(p));
    }
    const next: CableData = { ...d, ifaceA, ifaceB, labelA: ifaceA ?? "", labelB: ifaceB ?? "", active: true };
    // Nodes now have one handle per side ("s-t/r/b/l"); older cables point
    // at the removed target handles ("t-*").
    const targetHandle = edge.targetHandle?.startsWith("t-") ? `s-${edge.targetHandle.slice(2)}` : edge.targetHandle;
    const same =
      edge.type === "lab" && d.ifaceA === next.ifaceA && d.ifaceB === next.ifaceB &&
      d.labelA === next.labelA && d.labelB === next.labelB && d.active === true &&
      targetHandle === edge.targetHandle;
    if (same) {
      out.push(edge);
    } else {
      changed = true;
      out.push({ ...edge, type: "lab", targetHandle, data: next });
    }
  }
  return changed ? out : edges;
}

/** @deprecated use normalizeEdges (kept for older components). */
export const stampEdgeLabels = normalizeEdges;
