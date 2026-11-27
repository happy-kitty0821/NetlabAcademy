"use client";

/**
 * LinkDialog — choose the interface at each end of a new cable (CML-style).
 *
 * Shown when the user drags a connection between two devices. Each side
 * lists every port of that device: free ports are selectable, ports already
 * cabled show what they connect to. The first free port is preselected.
 * Enter connects, Escape cancels.
 */

import { useEffect, useMemo, useState } from "react";
import { Cable, X } from "lucide-react";
import type { Edge } from "@xyflow/react";
import type { DeviceNode } from "@/lib/deviceTypes";
import { cablePorts, usedPorts } from "@/lib/edgeLabels";

export function LinkDialog({
  source, target, nodes, edges, busy, error, onConnect, onCancel,
}: {
  source: DeviceNode;
  target: DeviceNode;
  nodes: DeviceNode[];
  edges: Edge[];
  busy?: boolean;
  error?: string | null;
  onConnect: (ifaceA: string, ifaceB: string) => void;
  onCancel: () => void;
}) {
  const sourceUsed = useMemo(() => usedPorts(source.id, nodes, edges), [source.id, nodes, edges]);
  const targetUsed = useMemo(() => usedPorts(target.id, nodes, edges), [target.id, nodes, edges]);
  const [ifaceA, setIfaceA] = useState(() => cablePorts(source).find((p) => !sourceUsed.has(p)) ?? "");
  const [ifaceB, setIfaceB] = useState(() => cablePorts(target).find((p) => !targetUsed.has(p)) ?? "");
  const canConnect = !!ifaceA && !!ifaceB && !busy;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter" && canConnect) onConnect(ifaceA, ifaceB);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canConnect, ifaceA, ifaceB, onCancel, onConnect]);

  return (
    <div
      role="presentation"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(31,35,40,0.35)]"
    >
      <div
        role="dialog" aria-modal="true" aria-labelledby="link-dialog-title"
        className="w-[520px] max-w-[calc(100vw-32px)] rounded-lg border border-[#d0d7de] bg-white shadow-[0_8px_24px_rgba(140,149,159,0.3)]"
      >
        <div className="flex items-center justify-between border-b border-[#d0d7de] px-4 py-3">
          <h2 id="link-dialog-title" className="flex items-center gap-2 text-sm font-semibold text-[#1f2328]">
            <Cable size={14} className="text-[#0969da]" aria-hidden="true" />
            Connect {source.data.hostname} to {target.data.hostname}
          </h2>
          <button onClick={onCancel} aria-label="Cancel" className="rounded p-1 text-[#656d76] hover:bg-[#f6f8fa]">
            <X size={14} />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3 p-4">
          <PortList node={source} used={sourceUsed} value={ifaceA} onChange={setIfaceA} />
          <PortList node={target} used={targetUsed} value={ifaceB} onChange={setIfaceB} />
        </div>

        {error && <p role="alert" className="px-4 pb-2 text-xs text-[#d1242f]">{error}</p>}

        <div className="flex items-center justify-between border-t border-[#d0d7de] px-4 py-3">
          <p className="font-mono text-xs text-[#656d76]">
            {source.data.hostname} {ifaceA || "—"} ↔ {target.data.hostname} {ifaceB || "—"}
          </p>
          <div className="flex gap-2">
            <button onClick={onCancel}
              className="rounded-md border border-[#d0d7de] bg-[#f6f8fa] px-3 py-1.5 text-xs text-[#1f2328] hover:bg-[#eaeef2]">
              Cancel
            </button>
            <button onClick={() => canConnect && onConnect(ifaceA, ifaceB)} disabled={!canConnect}
              className="rounded-md border border-[#1a7f37] bg-[#1f883d] px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
              {busy ? "Connecting…" : "Connect"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PortList({ node, used, value, onChange }: {
  node: DeviceNode; used: Map<string, string>; value: string; onChange: (p: string) => void;
}) {
  const ports = cablePorts(node);
  const free = ports.filter((p) => !used.has(p)).length;
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1.5 flex w-full items-baseline justify-between text-xs">
        <span className="font-semibold text-[#1f2328]">{node.data.hostname}</span>
        <span className="text-[#656d76]">{free} of {ports.length} free</span>
      </legend>
      <div role="radiogroup" aria-label={`${node.data.hostname} interface`}
        className="max-h-60 overflow-y-auto rounded-md border border-[#d0d7de]">
        {ports.map((port) => {
          const peer = used.get(port);
          const selected = value === port;
          return (
            <button
              key={port} type="button" role="radio" aria-checked={selected} disabled={!!peer}
              onClick={() => onChange(port)}
              className={
                "flex w-full items-center justify-between gap-2 border-b border-[#eaeef2] px-2.5 py-1.5 text-left font-mono text-xs last:border-b-0 " +
                (selected ? "bg-[#ddf4ff] text-[#0969da] " : "text-[#1f2328] hover:bg-[#f6f8fa] ") +
                (peer ? "cursor-not-allowed text-[#9198a1] hover:bg-transparent" : "")
              }
            >
              <span>{port}</span>
              <span className="truncate font-sans text-[11px] text-[#9198a1]">{peer ? `→ ${peer}` : selected ? "selected" : ""}</span>
            </button>
          );
        })}
        {ports.length === 0 && <p className="px-2.5 py-2 text-xs text-[#9198a1]">No cable ports</p>}
      </div>
    </fieldset>
  );
}
