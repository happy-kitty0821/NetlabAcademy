/**
 * Simulation API client — typed wrappers for the /api/v1/labs/simulations/ endpoints.
 */

import { apiFetch } from "./api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TopologyNode {
  id: string;
  model: "host" | "switch";
  hostname?: string;
  interfaces: {
    name: string;
    mac_seed?: number;
    ip?: string;
    gateway?: string;
  }[];
}

export interface TopologyLink {
  id: string;
  device_a: string;
  interface_a: string;
  device_b: string;
  interface_b: string;
}

export interface TopologyDocument {
  nodes: TopologyNode[];
  links: TopologyLink[];
}

export interface SimulationSession {
  id: string;
  seed: number;
  clock: number;
  device_count: number;
  link_count: number;
}

export interface EchoResultData {
  sequence: number;
  success: boolean;
  rtt_ticks: number | null;
  drop_reason: string | null;
}

export interface PingResultData {
  target_ip: string;
  count: number;
  sent: number;
  received: number;
  results: EchoResultData[];
}

export interface TraceEvent {
  type: string;
  time: number;
  seq: number;
  device_id?: string;
  switch_id?: string;
  src_device_id?: string;
  dst_device_id?: string;
  interface_name?: string;
  reason?: string;
  mac_address?: string;
  ip_address?: string;
  vlan?: number;
  message_type?: string;
  operation?: string;
  sender_ip?: string;
  target_ip?: string;
  icmp_type?: string;
  sequence?: number;
  limit?: number;
}

export interface PingResponse {
  ping: PingResultData;
  trace: TraceEvent[];
}

export interface DeviceState {
  id: string;
  hostname: string;
  model: string;
  interfaces: Record<string, {
    name: string;
    mac: string;
    admin_state: string;
    oper_state: string;
    ip: string | null;
    gateway: string | null;
    rx_frames: number;
    tx_frames: number;
  }>;
  arp_cache?: Record<string, string>;
  mac_table?: { mac: string; vlan: number; interface: string }[];
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function createSimulation(
  topology: TopologyDocument,
  seed: number = 42
): Promise<SimulationSession> {
  return apiFetch<SimulationSession>("/labs/simulations/", {
    method: "POST",
    body: JSON.stringify({ ...topology, seed }),
  });
}

export async function deleteSimulation(sessionId: string): Promise<void> {
  await apiFetch<void>(`/labs/simulations/${sessionId}/`, {
    method: "DELETE",
  });
}

export async function runPing(
  sessionId: string,
  deviceId: string,
  targetIp: string,
  count: number = 4
): Promise<PingResponse> {
  return apiFetch<PingResponse>(`/labs/simulations/${sessionId}/ping/`, {
    method: "POST",
    body: JSON.stringify({
      device_id: deviceId,
      target_ip: targetIp,
      count,
    }),
  });
}

export async function getTrace(sessionId: string): Promise<{ trace: TraceEvent[] }> {
  return apiFetch<{ trace: TraceEvent[] }>(`/labs/simulations/${sessionId}/trace/`);
}

export async function getDeviceState(
  sessionId: string,
  deviceId: string
): Promise<DeviceState> {
  return apiFetch<DeviceState>(
    `/labs/simulations/${sessionId}/devices/${deviceId}/`
  );
}

export async function resetSimulation(
  sessionId: string
): Promise<{ clock: number; trace: TraceEvent[] }> {
  return apiFetch<{ clock: number; trace: TraceEvent[] }>(
    `/labs/simulations/${sessionId}/reset/`,
    { method: "POST" }
  );
}

// ── Default topology ───────────────────────────────────────────────────────────

export const DEFAULT_TOPOLOGY: TopologyDocument = {
  nodes: [
    {
      id: "host-a",
      model: "host",
      hostname: "PC-A",
      interfaces: [{ name: "eth0", mac_seed: 10, ip: "192.168.1.1/24" }],
    },
    {
      id: "host-b",
      model: "host",
      hostname: "PC-B",
      interfaces: [{ name: "eth0", mac_seed: 11, ip: "192.168.1.2/24" }],
    },
    {
      id: "switch-1",
      model: "switch",
      hostname: "SW1",
      interfaces: [
        { name: "Gi0/0", mac_seed: 20 },
        { name: "Gi0/1", mac_seed: 21 },
      ],
    },
  ],
  links: [
    {
      id: "l1",
      device_a: "host-a",
      interface_a: "eth0",
      device_b: "switch-1",
      interface_b: "Gi0/0",
    },
    {
      id: "l2",
      device_a: "host-b",
      interface_a: "eth0",
      device_b: "switch-1",
      interface_b: "Gi0/1",
    },
  ],
};
