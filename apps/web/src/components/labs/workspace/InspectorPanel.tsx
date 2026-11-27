"use client";

/**
 * InspectorPanel — CML-style context pane on the right of the canvas.
 *
 *  - Nothing selected: the lab (devices, cables, how to cable).
 *  - A device: summary, Console / Edit actions, and every port with the
 *    device it connects to and, while running, its live link state.
 *  - A cable: both ends, live state of each end, and Unplug.
 */

import { useEffect, useMemo, useState } from "react";
import type { Edge } from "@xyflow/react";
import { Cable, ChevronRight, Pencil, Terminal, Trash2 } from "lucide-react";
import type { DeviceNode } from "@/lib/deviceTypes";
import { DEFAULT_DEVICE_CATALOG } from "@/lib/deviceTypes";
import { cablePorts, portOn, usedPorts } from "@/lib/edgeLabels";
import { getDeviceState, type DeviceState } from "@/lib/simulation-api";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";

export type Selection = { kind: "lab" } | { kind: "node"; id: string } | { kind: "edge"; id: string };

interface InspectorProps {
  selection:     Selection;
  nodes:         DeviceNode[];
  edges:         Edge[];
  labName:       string | null;
  simState:      SimState;
  sessionId:     string | null;
  /** Changes whenever new syslog arrives, to refresh live link states. */
  refreshKey:    number;
  onSelect:      (s: Selection) => void;
  onOpenConsole: (deviceId: string) => void;
  onEditNode:    (node: DeviceNode) => void;
  onDeleteEdge:  (edgeId: string) => void;
}

export function InspectorPanel(props: InspectorProps) {
  const { selection, nodes, edges } = props;
  const node = selection.kind === "node" ? nodes.find((n) => n.id === selection.id) : undefined;
  const edge = selection.kind === "edge" ? edges.find((e) => e.id === selection.id) : undefined;

  return (
    <aside className="flex w-72 shrink-0 flex-col overflow-y-auto border-l border-[#d0d7de] bg-white text-[#1f2328]">
      {node ? <NodeView {...props} node={node} />
        : edge ? <EdgeView {...props} edge={edge} />
        : <LabView {...props} />}
    </aside>
  );
}

// ── Live state ───────────────────────────────────────────────────────────────

function useDeviceStates(ids: string[], sessionId: string | null, running: boolean, refreshKey: number) {
  const [states, setStates] = useState<Record<string, DeviceState>>({});
  const key = ids.join(",");
  useEffect(() => {
    if (!running || !sessionId || !key) { setStates({}); return; }
    let cancelled = false;
    Promise.all(key.split(",").map((id) => getDeviceState(sessionId, id).catch(() => null)))
      .then((list) => {
        if (cancelled) return;
        setStates(Object.fromEntries(list.filter(Boolean).map((s) => [s!.id, s!])));
      });
    return () => { cancelled = true; };
  }, [key, sessionId, running, refreshKey]);
  return states;
}

function linkState(state: DeviceState | undefined, port: string | undefined, cabled = true) {
  const iface = port ? state?.interfaces[port] : undefined;
  if (!iface) return null;
  if (iface.admin_state === "DOWN") return { label: "admin down", color: "#9a6700" };
  if (iface.oper_state === "UP") return { label: "up", color: "#1a7f37" };
  // An unplugged port is not a fault (IOS calls it "notconnect").
  return cabled ? { label: "down", color: "#d1242f" } : { label: "notconnect", color: "#9198a1" };
}

// ── Views ────────────────────────────────────────────────────────────────────

function Header({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="border-b border-[#d0d7de] px-4 py-3">
      <h2 className="truncate text-sm font-semibold">{title}</h2>
      {subtitle && <p className="mt-0.5 text-xs text-[#656d76]">{subtitle}</p>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-[#eaeef2] px-4 py-3">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[#656d76]">{title}</h3>
      {children}
    </section>
  );
}

function ActionButton({ onClick, disabled, icon: Icon, children, danger }: {
  onClick: () => void; disabled?: boolean; icon: React.ElementType; children: React.ReactNode; danger?: boolean;
}) {
  return (
    <button onClick={onClick} disabled={disabled}
      className={"flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50 " +
        (danger ? "border-[#ffcecb] text-[#d1242f] hover:bg-[#ffebe9]" : "border-[#d0d7de] text-[#1f2328] hover:bg-[#f6f8fa]")}>
      <Icon size={12} aria-hidden="true" /> {children}
    </button>
  );
}

function LabView({ nodes, edges, labName, simState, onSelect }: InspectorProps) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return (
    <>
      <Header title={labName ?? "Untitled lab"} subtitle={`${nodes.length} devices · ${edges.length} links · ${simState === "running" ? "Started" : "Stopped"}`} />
      <Section title="Devices">
        {nodes.length === 0 ? (
          <p className="text-xs text-[#656d76]">Drag devices from the left panel onto the canvas.</p>
        ) : (
          <ul className="-mx-2">
            {nodes.map((n) => (
              <li key={n.id}>
                <button onClick={() => onSelect({ kind: "node", id: n.id })}
                  className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs hover:bg-[#f6f8fa]">
                  <span className="font-medium">{n.data.hostname}</span>
                  <span className="flex items-center gap-1 text-[#9198a1]">{modelName(n)} <ChevronRight size={11} /></span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Links">
        {edges.length === 0 ? (
          <p className="text-xs leading-relaxed text-[#656d76]">
            To cable two devices, drag from a blue dot on one device to another device,
            then choose the interface at each end.
          </p>
        ) : (
          <ul className="-mx-2">
            {edges.map((e) => (
              <li key={e.id}>
                <button onClick={() => onSelect({ kind: "edge", id: e.id })}
                  className="w-full rounded px-2 py-1 text-left font-mono text-[11px] hover:bg-[#f6f8fa]">
                  {byId.get(e.source)?.data.hostname} {portOn(e, e.source)} ↔ {byId.get(e.target)?.data.hostname} {portOn(e, e.target)}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}

function NodeView({ node, nodes, edges, simState, sessionId, refreshKey, onOpenConsole, onEditNode }: InspectorProps & { node: DeviceNode }) {
  const running = simState === "running";
  const states = useDeviceStates([node.id], sessionId, running, refreshKey);
  const used = useMemo(() => usedPorts(node.id, nodes, edges), [node.id, nodes, edges]);
  const ports = cablePorts(node);
  const showAll = node.data.model !== "host";
  const listed = showAll ? ports : ports.slice(0, 1);

  return (
    <>
      <Header title={String(node.data.hostname)} subtitle={modelName(node)} />
      <div className="flex gap-2 border-b border-[#eaeef2] px-4 py-2.5">
        <ActionButton onClick={() => onOpenConsole(node.id)} icon={Terminal}>Console</ActionButton>
        <ActionButton onClick={() => onEditNode(node)} icon={Pencil}>Edit</ActionButton>
      </div>
      {node.data.ip && (
        <Section title="Addressing">
          <p className="font-mono text-xs">{node.data.ip}</p>
          {node.data.gateway && <p className="mt-0.5 font-mono text-xs text-[#656d76]">gateway {node.data.gateway}</p>}
        </Section>
      )}
      <Section title={`Interfaces · ${used.size} of ${ports.length} connected`}>
        <table className="w-full text-xs">
          <tbody>
            {listed.map((port) => {
              const peer = used.get(port);
              const st = linkState(states[node.id], port, !!peer);
              return (
                <tr key={port} className="border-b border-[#f6f8fa] last:border-0">
                  <td className="py-1 pr-2 font-mono">{port}</td>
                  <td className="truncate py-1 pr-2 text-[#656d76]">{peer ?? <span className="text-[#d0d7de]">—</span>}</td>
                  <td className="py-1 text-right">
                    {running && st ? <span style={{ color: st.color }} className="font-medium">{st.label}</span>
                      : <span className="text-[#9198a1]">{peer ? "cabled" : ""}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Section>
    </>
  );
}

function EdgeView({ edge, nodes, simState, sessionId, refreshKey, onDeleteEdge, onSelect }: InspectorProps & { edge: Edge }) {
  const running = simState === "running";
  const a = nodes.find((n) => n.id === edge.source);
  const b = nodes.find((n) => n.id === edge.target);
  const states = useDeviceStates([edge.source, edge.target], sessionId, running, refreshKey);
  const ends = [
    { node: a, port: portOn(edge, edge.source) },
    { node: b, port: portOn(edge, edge.target) },
  ];
  return (
    <>
      <Header title="Link" subtitle={`${a?.data.hostname} ↔ ${b?.data.hostname}`} />
      <Section title="Endpoints">
        {ends.map(({ node, port }, i) => {
          const st = node ? linkState(states[node.id], port) : null;
          return (
            <button key={i} onClick={() => node && onSelect({ kind: "node", id: node.id })}
              className="-mx-2 flex w-[calc(100%+16px)] items-center justify-between rounded px-2 py-1.5 text-left text-xs hover:bg-[#f6f8fa]">
              <span><span className="font-medium">{node?.data.hostname}</span> <span className="font-mono text-[#656d76]">{port}</span></span>
              {running && st ? <span style={{ color: st.color }}>{st.label}</span> : null}
            </button>
          );
        })}
      </Section>
      <div className="flex gap-2 px-4 py-3">
        <ActionButton onClick={() => onDeleteEdge(edge.id)} icon={Trash2} danger>Unplug</ActionButton>
      </div>
      {!running && (
        <p className="flex items-start gap-1.5 px-4 text-xs text-[#656d76]">
          <Cable size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
          Start the lab to see whether this link is up.
        </p>
      )}
    </>
  );
}

function modelName(n: DeviceNode) {
  return DEFAULT_DEVICE_CATALOG.find((e) => e.id === n.data.catalogId)?.modelName ?? n.data.model;
}
