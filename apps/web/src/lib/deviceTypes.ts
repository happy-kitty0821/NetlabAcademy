/**
 * deviceTypes.ts
 * ──────────────
 * Shared device-model types used by the topology editor, the device
 * catalog, and the topology converter.
 *
 * Keeping these separate means the converter, the canvas nodes, and
 * the catalog panel all import from one place — no circular deps.
 */

import type { Node } from "@xyflow/react";

// ── Device catalog entry (defined by admin) ────────────────────────────────

export interface DeviceCatalogEntry {
  /** Unique key, e.g. "cisco-pc", "cisco-2960", "cisco-2911" */
  id: string;
  /** Display name shown in the palette */
  label: string;
  /** Friendly model identifier */
  modelName: string;
  /** Simulator model type */
  model: "host" | "switch" | "router";
  /** Icon identifier */
  icon: "pc" | "laptop" | "server" | "switch-l2" | "router";
  /** Whether the simulator supports this device type */
  simulated: boolean;
  /** Short description shown on hover */
  description: string;
}

// ── Flow node data ─────────────────────────────────────────────────────────

export interface DeviceNodeData extends Record<string, unknown> {
  hostname: string;
  model: "host" | "switch" | "router";
  catalogId: string;        // references DeviceCatalogEntry.id
  ip?: string;              // CIDR, e.g. "192.168.1.1/24" (hosts/routers)
  gateway?: string;
}

export type DeviceNode = Node<DeviceNodeData>;

// ── Built-in Cisco-style device catalog ───────────────────────────────────
// This is the default catalog used when no admin-defined catalog exists.
// An admin panel (future spec) will allow adding/editing entries.

export const DEFAULT_DEVICE_CATALOG: DeviceCatalogEntry[] = [
  {
    id: "cisco-pc",
    label: "PC",
    modelName: "End Device — PC",
    model: "host",
    icon: "pc",
    simulated: true,
    description: "Generic end-host PC. Supports IPv4, ARP, ICMP ping.",
  },
  {
    id: "cisco-laptop",
    label: "Laptop",
    modelName: "End Device — Laptop",
    model: "host",
    icon: "laptop",
    simulated: true,
    description: "Wireless-capable end-host. Same simulation model as PC.",
  },
  {
    id: "cisco-server",
    label: "Server",
    modelName: "Generic Server",
    model: "host",
    icon: "server",
    simulated: true,
    description: "Server end-host. Same simulation model as PC.",
  },
  {
    id: "cisco-2960",
    label: "2960 Switch",
    modelName: "Cisco Catalyst 2960",
    model: "switch",
    icon: "switch-l2",
    simulated: true,
    description: "Layer 2 Ethernet switch. Supports MAC learning and forwarding.",
  },
  {
    id: "cisco-2911",
    label: "2911 Router",
    modelName: "Cisco 2911 Router",
    model: "router",
    icon: "router",
    simulated: true,
    description: "Layer 3 router. Supports static routing, ip route commands, show ip route.",
  },
];
