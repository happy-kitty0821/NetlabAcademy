/**
 * Saved-lab client for /api/v1/labs/labs/.
 *
 * A saved lab stores the workspace canvas exactly as drawn (React Flow
 * nodes with positions, and edges), so reopening it restores the layout.
 * Labs are private to their owner; another user's lab returns 404.
 */

import type { Edge } from "@xyflow/react";
import { apiFetch } from "./api";
import type { DeviceNode } from "./deviceTypes";

export interface LabSummary {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  device_count: number;
  link_count: number;
}

export interface LabTopology {
  nodes: DeviceNode[];
  edges: Edge[];
}

export interface Lab {
  id: string;
  name: string;
  description: string;
  topology: LabTopology;
  created_at: string;
  updated_at: string;
  owner_name: string;
}

export async function listLabs(): Promise<LabSummary[]> {
  return apiFetch<LabSummary[]>("/labs/labs/");
}

export async function getLab(id: string): Promise<Lab> {
  return apiFetch<Lab>(`/labs/labs/${id}/`);
}

export async function createLab(data: {
  name: string;
  description?: string;
  topology: LabTopology;
}): Promise<Lab> {
  return apiFetch<Lab>("/labs/labs/", { method: "POST", body: JSON.stringify(data) });
}

export async function updateLab(
  id: string,
  changes: Partial<{ name: string; description: string; topology: LabTopology }>,
): Promise<Lab> {
  return apiFetch<Lab>(`/labs/labs/${id}/`, { method: "PATCH", body: JSON.stringify(changes) });
}

export async function deleteLab(id: string): Promise<void> {
  return apiFetch<void>(`/labs/labs/${id}/`, { method: "DELETE" });
}

/**
 * The canvas as it should be stored: drops React Flow's transient UI state
 * (selection, dragging, measured sizes) so saving after merely clicking a
 * node does not count as a change.
 */
export function canvasForSaving(nodes: DeviceNode[], edges: Edge[]): LabTopology {
  return {
    nodes: nodes.map(({ id, type, position, data }) => ({ id, type, position, data }) as DeviceNode),
    edges: edges.map(({ id, source, target, sourceHandle, targetHandle, type, data }) =>
      ({ id, source, target, sourceHandle, targetHandle, type, data }) as Edge),
  };
}

/** True when the id looks like a saved-lab UUID (curated labs use slugs). */
export function isLabId(value: string | null): value is string {
  return !!value && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

/** Human-readable message from an API error. */
export function labErrorText(err: unknown): string {
  const e = (err as { error?: { message?: string; detail?: Record<string, unknown> } })?.error;
  if (!e) return "Could not reach the server.";
  if (e.detail) {
    const first = Object.values(e.detail).flat()[0];
    if (first) return String(first);
  }
  return e.message ?? "Request failed.";
}
