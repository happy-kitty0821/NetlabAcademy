"use client";

/**
 * TopologyEditor
 * ──────────────
 * Drag-and-drop network topology canvas built on React Flow / XYFlow.
 *
 * Features:
 *  - Add PC or Switch nodes via toolbar buttons
 *  - Draw links by dragging from a handle to another node
 *  - Double-click a node to configure hostname + IP address inline
 *  - Delete selected nodes/edges with the Delete or Backspace key
 *  - "Use this topology" validates and passes the converted TopologyDocument
 *    to the parent
 *  - State persisted to sessionStorage on every change; restored on mount
 *  - "Reset to default" clears session storage
 *
 * No CSS variables are used inside SVG — colors are explicit hex strings
 * defined in FlowNodes.tsx and this file.
 */

import "@xyflow/react/dist/style.css";

import {
  useCallback,
  useEffect,
  useState,
} from "react";
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
  type Node,
  BackgroundVariant,
} from "@xyflow/react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { nodeTypes } from "./FlowNodes";
import {
  convertFlowToTopology,
  TopologyValidationError,
  type DeviceNode,
  type DeviceNodeData,
} from "@/lib/convertFlowToTopology";
import type { TopologyDocument } from "@/lib/simulation-api";
import { Monitor, Network, RotateCcw, CheckCircle2 } from "lucide-react";

// ── Session storage key ───────────────────────────────────────────────────────

const STORAGE_KEY = "netlab_topology_editor";

// ── Default starting state ────────────────────────────────────────────────────

const DEFAULT_NODES: DeviceNode[] = [
  {
    id: "host-a",
    type: "pc",
    position: { x: 60, y: 140 },
    data: { hostname: "PC-A", model: "host", ip: "192.168.1.1/24" },
  },
  {
    id: "host-b",
    type: "pc",
    position: { x: 440, y: 140 },
    data: { hostname: "PC-B", model: "host", ip: "192.168.1.2/24" },
  },
  {
    id: "switch-1",
    type: "switch",
    position: { x: 230, y: 130 },
    data: { hostname: "SW1", model: "switch" },
  },
];

const DEFAULT_EDGES: Edge[] = [
  { id: "l1", source: "host-a", target: "switch-1" },
  { id: "l2", source: "host-b", target: "switch-1" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

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
    /* quota exceeded — ignore */
  }
}

let nodeCounter = 100;
function newNodeId() {
  return `node-${++nodeCounter}`;
}

// ── Config overlay ────────────────────────────────────────────────────────────

interface ConfigPanelProps {
  node: DeviceNode;
  onSave: (id: string, data: Partial<DeviceNodeData>) => void;
  onClose: () => void;
}

function ConfigPanel({ node, onSave, onClose }: ConfigPanelProps) {
  const [hostname, setHostname] = useState(node.data.hostname);
  const [ip, setIp] = useState(node.data.ip ?? "");
  const [ipError, setIpError] = useState("");

  function validateIp(v: string) {
    if (!v) { setIpError(""); return; }
    const parts = v.split("/");
    if (parts.length !== 2) { setIpError("Use CIDR format: 192.168.1.1/24"); return; }
    const prefix = parseInt(parts[1]);
    if (isNaN(prefix) || prefix < 0 || prefix > 32) {
      setIpError("Prefix must be 0–32");
      return;
    }
    setIpError("");
  }

  function handleSave() {
    if (node.data.model === "host" && ip && ipError) return;
    onSave(node.id, {
      hostname: hostname.trim() || node.data.hostname,
      ip: node.data.model === "host" ? ip.trim() || undefined : undefined,
    });
    onClose();
  }

  return (
    <div
      className="absolute z-30 rounded-xl border border-[#30363d] bg-[#161b22] shadow-2xl"
      style={{ top: 8, right: 8, width: 240 }}
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#30363d]">
        <span className="text-sm font-semibold text-[#e6edf3]">
          Configure device
        </span>
        <button
          onClick={onClose}
          className="text-[#8b949e] hover:text-[#e6edf3] text-lg leading-none"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div className="p-4 space-y-3">
        <Input
          label="Hostname"
          value={hostname}
          onChange={(e) => setHostname(e.target.value)}
          placeholder="PC-A"
        />
        {node.data.model === "host" && (
          <Input
            label="IP Address (CIDR)"
            value={ip}
            onChange={(e) => { setIp(e.target.value); validateIp(e.target.value); }}
            placeholder="192.168.1.1/24"
            error={ipError}
            hint="e.g. 192.168.1.1/24"
          />
        )}
        <div className="flex gap-2 pt-1">
          <Button size="sm" onClick={handleSave} className="flex-1">
            <CheckCircle2 size={12} aria-hidden="true" />
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
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

  // Persist on every change
  useEffect(() => {
    saveToStorage(nodes, edges);
  }, [nodes, edges]);

  // Config panel state
  const [editingNode, setEditingNode] = useState<DeviceNode | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [applySuccess, setApplySuccess] = useState(false);

  // ── Callbacks ─────────────────────────────────────────────────────────────

  const onConnect = useCallback(
    (connection: Connection) =>
      setEdges((eds) => addEdge({ ...connection, id: `e-${Date.now()}` }, eds)),
    [setEdges],
  );

  const addDevice = useCallback(
    (model: "host" | "switch") => {
      const id = newNodeId();
      const isHost = model === "host";
      const count = nodes.filter((n) => n.data.model === model).length;
      const newNode: DeviceNode = {
        id,
        type: isHost ? "pc" : "switch",
        position: {
          x: 100 + (nodes.length % 4) * 140,
          y: 80 + Math.floor(nodes.length / 4) * 160,
        },
        data: {
          hostname: isHost ? `PC-${String.fromCharCode(65 + count)}` : `SW${count + 1}`,
          model,
          ip: isHost ? "" : undefined,
        },
      };
      setNodes((nds) => [...nds, newNode]);
    },
    [nodes, setNodes],
  );

  const onNodeDoubleClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setEditingNode(node as DeviceNode);
    },
    [],
  );

  const saveNodeConfig = useCallback(
    (id: string, data: Partial<DeviceNodeData>) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === id ? { ...n, data: { ...n.data, ...data } } : n,
        ),
      );
      setEditingNode(null);
    },
    [setNodes],
  );

  const handleApply = useCallback(() => {
    setValidationError(null);
    setApplySuccess(false);
    try {
      const topo = convertFlowToTopology(nodes, edges);
      onApply(topo);
      setApplySuccess(true);
      setTimeout(() => setApplySuccess(false), 3000);
    } catch (err) {
      if (err instanceof TopologyValidationError) {
        setValidationError(err.message);
      } else {
        setValidationError("Unexpected error converting topology.");
      }
    }
  }, [nodes, edges, onApply]);

  const handleReset = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
    setNodes(DEFAULT_NODES);
    setEdges(DEFAULT_EDGES);
    setValidationError(null);
    setApplySuccess(false);
  }, [setNodes, setEdges]);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-3">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-[var(--text-muted)] font-mono mr-1">
          Add device:
        </span>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => addDevice("host")}
          aria-label="Add PC"
        >
          <Monitor size={13} aria-hidden="true" />
          PC
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => addDevice("switch")}
          aria-label="Add Switch"
        >
          <Network size={13} aria-hidden="true" />
          Switch
        </Button>

        <div className="flex-1" />

        <Button
          size="sm"
          variant="ghost"
          onClick={handleReset}
          aria-label="Reset to default topology"
        >
          <RotateCcw size={13} aria-hidden="true" />
          Reset
        </Button>
        <Button
          size="sm"
          variant={applySuccess ? "secondary" : "primary"}
          onClick={handleApply}
          aria-label="Use this topology for simulation"
        >
          <CheckCircle2 size={13} aria-hidden="true" />
          {applySuccess ? "Applied!" : "Use this topology"}
        </Button>
      </div>

      {/* Hint */}
      <p className="text-[11px] text-[var(--text-muted)]">
        Drag from a node handle to connect devices. Double-click a device to configure it.
        Select a node or link and press Delete to remove it.
      </p>

      {/* Validation error */}
      {validationError && (
        <div
          role="alert"
          className="rounded-md px-3 py-2 text-xs bg-[#3a1a1a] border border-[#f85149] text-[#f85149]"
        >
          {validationError}
        </div>
      )}

      {/* Canvas */}
      <div className="relative rounded-lg overflow-hidden border border-[#30363d]" style={{ height: 380 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDoubleClick={onNodeDoubleClick}
          nodeTypes={nodeTypes}
          deleteKeyCode={["Delete", "Backspace"]}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          style={{ background: "#0d1117" }}
          defaultEdgeOptions={{
            style: { stroke: "#30363d", strokeWidth: 2 },
            animated: false,
          }}
          proOptions={{ hideAttribution: true }}
          aria-label="Network topology canvas"
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={24}
            size={1}
            color="#21262d"
          />
          <Controls
            style={{ background: "#161b22", border: "1px solid #30363d" }}
          />
          <MiniMap
            style={{ background: "#161b22", border: "1px solid #30363d" }}
            nodeColor="#30363d"
            maskColor="rgba(13,17,23,0.7)"
          />
        </ReactFlow>

        {/* Inline config panel */}
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
