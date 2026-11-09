"use client";

/**
 * TopologyEditor — EVE-NG style topology canvas.
 *
 * Cables render with green color (active Ethernet) and interface name
 * labels at each endpoint — same visual language as EVE-NG.
 */

import "@xyflow/react/dist/style.css";

import { useCallback, useEffect, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Edge,
  BackgroundVariant,
} from "@xyflow/react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { nodeTypes } from "./FlowNodes";
import { edgeTypes } from "./FlowEdge";
import {
  convertFlowToTopology,
  TopologyValidationError,
  type DeviceNode,
} from "@/lib/convertFlowToTopology";
import {
  DEFAULT_DEVICE_CATALOG,
  type DeviceCatalogEntry,
  type DeviceNodeData,
} from "@/lib/deviceTypes";
import type { TopologyDocument } from "@/lib/simulation-api";
import { RotateCcw, CheckCircle2, Monitor, Network, Server, Laptop } from "lucide-react";

// ── Storage ───────────────────────────────────────────────────────────────────

const STORAGE_KEY = "netlab_topo_v2";

function loadFromStorage(): { nodes: DeviceNode[]; edges: Edge[] } | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as { nodes: DeviceNode[]; edges: Edge[] };
  } catch {
    return null;
  }
}

function saveToStorage(nodes: DeviceNode[], edges: Edge[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ nodes, edges }));
  } catch {
    // quota exceeded — ignore
  }
}

// ── Default topology (2 PCs + 1 switch) ──────────────────────────────────────

const DEFAULT_NODES: DeviceNode[] = [
  {
    id: "host-a",
    type: "cisco-pc",
    position: { x: 60, y: 120 },
    data: { hostname: "PC-A", model: "host", catalogId: "cisco-pc", ip: "192.168.1.1/24" },
  },
  {
    id: "host-b",
    type: "cisco-pc",
    position: { x: 440, y: 120 },
    data: { hostname: "PC-B", model: "host", catalogId: "cisco-pc", ip: "192.168.1.2/24" },
  },
  {
    id: "switch-1",
    type: "cisco-2960",
    position: { x: 230, y: 100 },
    data: { hostname: "SW1", model: "switch", catalogId: "cisco-2960" },
  },
];

const DEFAULT_EDGES: Edge[] = [
  {
    id: "l1", source: "host-a", target: "switch-1", type: "lab",
    data: { labelA: "eth0", labelB: "Gi0/0", active: true },
  },
  {
    id: "l2", source: "host-b", target: "switch-1", type: "lab",
    data: { labelA: "eth0", labelB: "Gi0/1", active: true },
  },
];

// ── Node counter ──────────────────────────────────────────────────────────────

let _counter = 100;
function nextId() { return `n-${++_counter}`; }

// ── Stamp interface labels onto edges ─────────────────────────────────────────
// Runs the same pre-assignment pass as convertFlowToTopology but only returns
// the enriched edges — used after any topology change to keep labels in sync.

function stampEdgeLabels(
  currentNodes: DeviceNode[],
  currentEdges: Edge[],
): Edge[] {
  const nodeMap = new Map(currentNodes.map((n) => [n.id, n]));
  const counter = new Map<string, number>();

  return currentEdges.map((edge) => {
    function getIface(nodeId: string): string {
      const node = nodeMap.get(nodeId);
      if (!node || node.data.model === "host") return "eth0";
      const c = counter.get(nodeId) ?? 0;
      counter.set(nodeId, c + 1);
      return `Gi0/${c}`;
    }
    const labelA = getIface(edge.source);
    const labelB = getIface(edge.target);
    return {
      ...edge,
      type: "lab",
      data: { ...edge.data, labelA, labelB, active: true },
    };
  });
}

// ── Catalog icon map ──────────────────────────────────────────────────────────

function CatalogIcon({ icon }: { icon: DeviceCatalogEntry["icon"] }) {
  const s = { width: 14, height: 14, "aria-hidden": true } as const;
  if (icon === "switch-l2") return <Network {...s} />;
  if (icon === "router")    return <Network {...s} />;
  if (icon === "laptop")    return <Laptop {...s} />;
  if (icon === "server")    return <Server {...s} />;
  return <Monitor {...s} />;
}

// ── Config panel ──────────────────────────────────────────────────────────────

function ConfigPanel({
  node,
  onSave,
  onClose,
}: {
  node: DeviceNode;
  onSave: (id: string, patch: Partial<DeviceNodeData>) => void;
  onClose: () => void;
}) {
  const [hostname, setHostname] = useState(String(node.data.hostname));
  const [ip, setIp] = useState(String(node.data.ip ?? ""));
  const [ipErr, setIpErr] = useState("");

  function checkIp(v: string) {
    if (!v) { setIpErr(""); return; }
    const p = v.split("/");
    if (p.length !== 2 || isNaN(parseInt(p[1]))) {
      setIpErr("Use CIDR format: 192.168.1.1/24");
    } else {
      setIpErr("");
    }
  }

  function save() {
    if (node.data.model === "host" && ip && ipErr) return;
    onSave(node.id, {
      hostname: hostname.trim() || String(node.data.hostname),
      ip: node.data.model === "host" ? ip.trim() || undefined : undefined,
    });
    onClose();
  }

  return (
    <div className="absolute z-30 top-2 right-2 w-60 rounded-xl border border-[#30363d] bg-[#161b22] shadow-2xl">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#30363d]">
        <span className="text-sm font-semibold text-[#e6edf3]">Configure device</span>
        <button onClick={onClose} className="text-[#8b949e] hover:text-[#e6edf3] text-lg" aria-label="Close">✕</button>
      </div>
      <div className="p-4 space-y-3">
        <Input label="Hostname" value={hostname} onChange={(e) => setHostname(e.target.value)} placeholder="PC-A" />
        {node.data.model === "host" && (
          <Input
            label="IP Address (CIDR)"
            value={ip}
            onChange={(e) => { setIp(e.target.value); checkIp(e.target.value); }}
            placeholder="192.168.1.1/24"
            error={ipErr}
            hint="e.g. 192.168.1.1/24"
          />
        )}
        <div className="flex gap-2 pt-1">
          <Button size="sm" onClick={save} className="flex-1">
            <CheckCircle2 size={12} aria-hidden="true" />
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </div>
  );
}

// ── Device palette item ───────────────────────────────────────────────────────

function PaletteItem({
  entry,
  onAdd,
}: {
  entry: DeviceCatalogEntry;
  onAdd: (entry: DeviceCatalogEntry) => void;
}) {
  return (
    <button
      onClick={() => !entry.simulated && entry.model === "switch" && entry.icon === "router"
        ? undefined    // router not yet simulated — no-op visual
        : onAdd(entry)
      }
      disabled={!entry.simulated && entry.icon === "router"}
      title={entry.description}
      className="flex flex-col items-center gap-1 px-3 py-2 rounded-lg border border-[#30363d] bg-[#161b22]
        hover:border-[#58a6ff] hover:bg-[#1d3558] transition-colors cursor-pointer
        disabled:opacity-40 disabled:cursor-not-allowed text-center min-w-[64px]"
      aria-label={`Add ${entry.label}`}
    >
      <CatalogIcon icon={entry.icon} />
      <span className="text-[10px] font-mono text-[#e6edf3] leading-tight">{entry.label}</span>
      {!entry.simulated && (
        <span className="text-[9px] text-[#f85149]">soon</span>
      )}
    </button>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface TopologyEditorProps {
  onApply: (topo: TopologyDocument) => void;
}

export function TopologyEditor({ onApply }: TopologyEditorProps) {
  const saved = loadFromStorage();
  const [nodes, setNodes, onNodesChange] = useNodesState<DeviceNode>(
    saved?.nodes ?? DEFAULT_NODES,
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState(
    saved?.edges ?? DEFAULT_EDGES,
  );

  // Save on every graph change; also re-stamp edge labels when edges change
  useEffect(() => {
    saveToStorage(nodes, edges);
  }, [nodes, edges]);

  // Re-stamp interface labels whenever nodes are added/deleted
  // (a deleted node changes port numbering on switches)
  useEffect(() => {
    setEdges((eds) => stampEdgeLabels(nodes, eds));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes]);

  const [editingNode, setEditingNode] = useState<DeviceNode | null>(null);
  const [validationErr, setValidationErr] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);

  // ── Connect ───────────────────────────────────────────────────────────────

  const onConnect = useCallback(
    (conn: Connection) => {
      setEdges((eds) => {
        const newEdges = addEdge(
          { ...conn, id: `e-${Date.now()}`, type: "lab" },
          eds,
        );
        // Re-stamp all labels so the new edge gets correct interface names
        return stampEdgeLabels(nodes, newEdges);
      });
    },
    [nodes, setEdges],
  );

  // ── Add device from catalog ───────────────────────────────────────────────

  const addDevice = useCallback(
    (entry: DeviceCatalogEntry) => {
      const id = nextId();
      const count = nodes.filter((n) => n.data.catalogId === entry.id).length;

      const hostnameDefault =
        entry.icon === "pc"       ? `PC-${String.fromCharCode(65 + count)}`
        : entry.icon === "laptop" ? `Laptop-${count + 1}`
        : entry.icon === "server" ? `Server-${count + 1}`
        : entry.icon === "router" ? `R${count + 1}`
        : `SW${count + 1}`;

      const newNode: DeviceNode = {
        id,
        type: entry.id,
        position: {
          x: 80 + (nodes.length % 4) * 150,
          y: 80 + Math.floor(nodes.length / 4) * 180,
        },
        data: {
          hostname: hostnameDefault,
          model: entry.model,
          catalogId: entry.id,
          ip: entry.model === "host" ? "" : undefined,
        },
      };
      setNodes((nds) => [...nds, newNode]);
    },
    [nodes, setNodes],
  );

  // ── Double-click to configure ─────────────────────────────────────────────

  const onNodeDoubleClick = useCallback(
    (_: React.MouseEvent, node: unknown) => {
      setEditingNode(node as DeviceNode);
    },
    [],
  );

  const saveNodeConfig = useCallback(
    (id: string, patch: Partial<DeviceNodeData>) => {
      setNodes((nds) =>
        nds.map((n) => n.id === id ? { ...n, data: { ...n.data, ...patch } } : n),
      );
      setEditingNode(null);
    },
    [setNodes],
  );

  // ── Apply ─────────────────────────────────────────────────────────────────

  const handleApply = useCallback(() => {
    setValidationErr(null);
    setApplied(false);
    try {
      const result = convertFlowToTopology(nodes, edges);
      onApply(result.topology);
      setApplied(true);
      setTimeout(() => setApplied(false), 3000);
    } catch (err) {
      setValidationErr(
        err instanceof TopologyValidationError
          ? err.message
          : "Unexpected error building topology.",
      );
    }
  }, [nodes, edges, onApply]);

  const handleReset = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
    setNodes(DEFAULT_NODES);
    setEdges(DEFAULT_EDGES);
    setValidationErr(null);
    setApplied(false);
  }, [setNodes, setEdges]);

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-3">

      {/* Device palette */}
      <div>
        <p className="text-[11px] font-mono text-[var(--text-muted)] mb-2">Device palette</p>
        <div className="flex flex-wrap gap-2">
          {DEFAULT_DEVICE_CATALOG.map((entry) => (
            <PaletteItem key={entry.id} entry={entry} onAdd={addDevice} />
          ))}
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-[11px] font-mono text-[var(--text-muted)] flex-1">
          Drag from a handle to connect · Double-click to configure · Delete/Backspace to remove
        </p>
        <Button size="sm" variant="ghost" onClick={handleReset} aria-label="Reset to default">
          <RotateCcw size={12} aria-hidden="true" />
          Reset
        </Button>
        <Button
          size="sm"
          variant={applied ? "secondary" : "primary"}
          onClick={handleApply}
          aria-label="Use this topology"
        >
          <CheckCircle2 size={12} aria-hidden="true" />
          {applied ? "Applied!" : "Use this topology"}
        </Button>
      </div>

      {/* Validation error */}
      {validationErr && (
        <div role="alert" className="text-xs px-3 py-2 rounded-md bg-[#3a1a1a] border border-[#f85149] text-[#f85149]">
          {validationErr}
        </div>
      )}

      {/* Canvas */}
      <div className="relative rounded-lg overflow-hidden border border-[#30363d]" style={{ height: 400 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDoubleClick={onNodeDoubleClick}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          deleteKeyCode={["Delete", "Backspace"]}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          style={{ background: "#0d1117" }}
          defaultEdgeOptions={{
            type: "lab",
            data: { labelA: "", labelB: "", active: true },
          }}
          proOptions={{ hideAttribution: true }}
          aria-label="Network topology canvas"
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#21262d" />
          <Controls style={{ background: "#161b22", border: "1px solid #30363d" }} />
          <MiniMap
            style={{ background: "#161b22", border: "1px solid #30363d" }}
            nodeColor="#30363d"
            maskColor="rgba(13,17,23,0.7)"
          />
        </ReactFlow>

        {editingNode && (
          <ConfigPanel
            node={editingNode}
            onSave={saveNodeConfig}
            onClose={() => setEditingNode(null)}
          />
        )}
      </div>
    </div>
  );
}
