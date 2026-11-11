"use client";

import { useCallback, useRef, useState, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  BackgroundVariant,
  addEdge,
  useNodesState,
  useEdgesState,
  SelectionMode,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/base.css";

import { nodeTypes }         from "@/components/labs/FlowNodes";
import { edgeTypes }         from "@/components/labs/FlowEdge";
import { stampEdgeLabels }   from "@/lib/edgeLabels";
import { convertFlowToTopology, TopologyValidationError } from "@/lib/convertFlowToTopology";
import type { DeviceNode }   from "@/lib/convertFlowToTopology";
import type { DeviceNodeData } from "@/lib/deviceTypes";
import { DEFAULT_DEVICE_CATALOG } from "@/lib/deviceTypes";
import { createSimulation, resetSimulation } from "@/lib/simulation-api";
import type { TopologyDocument, TopologyNode, TraceEvent } from "@/lib/simulation-api";

import { WorkspaceToolbar } from "@/components/labs/workspace/WorkspaceToolbar";
import { DevicePalette }    from "@/components/labs/workspace/DevicePalette";
import { NodeConfigPopup }  from "@/components/labs/workspace/NodeConfigPopup";
import { NodeSidePanel }    from "@/components/labs/workspace/NodeSidePanel";
import { BottomPanel }      from "@/components/labs/workspace/BottomPanel";

export type SimState = "stopped" | "starting" | "running" | "stopping";

// ── Storage ───────────────────────────────────────────────────────────────────
// Use v4 key so stale data from old sessions doesn't load
const STORAGE_KEY = "netlab_canvas_v4";

// Clear any old storage keys from previous versions
const OLD_KEYS = ["netlab_canvas_v3", "netlab_canvas_v2", "netlab_topo_v2"];

function clearOldStorage() {
  if (typeof window === "undefined") return;
  OLD_KEYS.forEach((k) => {
    try { sessionStorage.removeItem(k); } catch { /* ignore */ }
  });
}

function loadCanvas(): { nodes: DeviceNode[]; edges: Edge[] } | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function saveCanvas(nodes: DeviceNode[], edges: Edge[]) {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ nodes, edges })); }
  catch { /* quota */ }
}

// ── ID counter ────────────────────────────────────────────────────────────────
let _counter = 100;
function bumpCounter(nodes: DeviceNode[]) {
  for (const n of nodes) {
    const m = n.id.match(/^n-(\d+)$/);
    if (m) { const v = parseInt(m[1]); if (v >= _counter) _counter = v + 1; }
  }
}
function nextId() { return `n-${++_counter}`; }

// ── Page component ────────────────────────────────────────────────────────────

export default function WorkspacePage() {
  // Clear stale storage from old sessions on first render
  useEffect(() => { clearOldStorage(); }, []);

  const [nodes, setNodes, onNodesChange] = useNodesState<DeviceNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // Load persisted canvas after mount (avoid SSR mismatch)
  useEffect(() => {
    const saved = loadCanvas();
    if (saved?.nodes?.length) {
      bumpCounter(saved.nodes);
      setNodes(saved.nodes);
      setEdges(saved.edges ?? []);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist on every change
  useEffect(() => { saveCanvas(nodes, edges); }, [nodes, edges]);

  // Re-stamp interface labels when node count changes
  useEffect(() => {
    setEdges((eds) => stampEdgeLabels(nodes, eds));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes.length]);

  // ── Sim state ──────────────────────────────────────────────────────────────
  const [simState,  setSimState]  = useState<SimState>("stopped");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [topology,  setTopology]  = useState<TopologyDocument | null>(null);
  const [simError,  setSimError]  = useState<string | null>(null);
  const [trace,     setTrace]     = useState<TraceEvent[]>([]);

  // ── Selection ──────────────────────────────────────────────────────────────
  const [selectedNode, setSelectedNode] = useState<DeviceNode | null>(null);
  const [configNode,   setConfigNode]   = useState<DeviceNode | null>(null);
  const [rightTab,     setRightTab]     = useState<"properties" | "interfaces">("properties");

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rfInstanceRef = useRef<any>(null);
  const canvasRef     = useRef<HTMLDivElement>(null);

  // ── Connect wire ──────────────────────────────────────────────────────────
  const onConnect = useCallback((conn: Connection) => {
    setEdges((eds) => stampEdgeLabels(nodes, addEdge(
      { ...conn, id: `e-${Date.now()}`, type: "lab", data: { active: true } }, eds,
    )));
  }, [nodes, setEdges]);

  // ── Drag-drop from palette ────────────────────────────────────────────────
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const catalogId = e.dataTransfer.getData("application/netlab-device");
    if (!catalogId || !rfInstanceRef.current || !canvasRef.current) return;

    const entry = DEFAULT_DEVICE_CATALOG.find((d) => d.id === catalogId);
    if (!entry) return;

    const bounds   = canvasRef.current.getBoundingClientRect();
    const position = rfInstanceRef.current.screenToFlowPosition({
      x: e.clientX - bounds.left,
      y: e.clientY - bounds.top,
    });

    const id    = nextId();
    const count = nodes.filter((n) => n.data.catalogId === entry.id).length;
    const hostname =
      entry.icon === "pc"       ? `PC-${String.fromCharCode(65 + count)}`
      : entry.icon === "laptop" ? `Laptop-${count + 1}`
      : entry.icon === "server" ? `Server-${count + 1}`
      : entry.icon === "router" ? `R${count + 1}`
      : `SW${count + 1}`;

    const newNode: DeviceNode = {
      id, type: entry.id, position,
      data: { hostname, model: entry.model, catalogId: entry.id,
              ip: entry.model === "host" ? "" : undefined },
    };

    setNodes((nds) => [...nds, newNode]);
    setConfigNode(newNode);
  }, [nodes, setNodes]);

  // ── Node interactions ─────────────────────────────────────────────────────
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node as DeviceNode);
    setRightTab("properties");
  }, []);

  const onNodeDoubleClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node as DeviceNode);
    if (simState === "running" && sessionId) {
      // Double-click opens the bottom terminal panel (not right panel)
      setRightTab("properties");
    } else {
      setConfigNode(node as DeviceNode);
    }
  }, [simState, sessionId]);

  const onPaneClick = useCallback(() => setSelectedNode(null), []);

  const saveConfig = useCallback((id: string, patch: Partial<DeviceNodeData>) => {
    setNodes((nds) => nds.map((n) => n.id === id ? { ...n, data: { ...n.data, ...patch } } : n));
    setConfigNode(null);
  }, [setNodes]);

  // ── Simulation handlers ───────────────────────────────────────────────────
  const handleStart = useCallback(async () => {
    setSimError(null);
    setSimState("starting");
    setTrace([]);
    try {
      const { topology: topo } = convertFlowToTopology(nodes, edges);
      const session = await createSimulation(topo, 42);
      setTopology(topo);
      setSessionId(session.id);
      setSimState("running");
    } catch (err) {
      setSimError(err instanceof TopologyValidationError
        ? err.message
        : ((err as { error?: { message?: string } })?.error?.message ?? "Failed to start."));
      setSimState("stopped");
    }
  }, [nodes, edges]);

  const handleStop = useCallback(() => {
    setSimState("stopping");
    setTimeout(() => { setSimState("stopped"); setSessionId(null); setTopology(null); }, 300);
  }, []);

  const handleWipe = useCallback(async () => {
    if (sessionId) { try { await resetSimulation(sessionId); } catch { /**/ } }
    setTrace([]); setSimState("stopped"); setSessionId(null);
    setTopology(null); setSimError(null);
  }, [sessionId]);

  const handleClearCanvas = useCallback(() => {
    setNodes([]); setEdges([]);
    setSelectedNode(null); setConfigNode(null);
    sessionStorage.removeItem(STORAGE_KEY);
    handleWipe();
  }, [setNodes, setEdges, handleWipe]);

  const topoNode: TopologyNode | null =
    selectedNode && topology
      ? topology.nodes.find((n) => n.id === selectedNode.id) ?? null
      : null;

  return (
    <div className="flex flex-col h-full bg-white overflow-hidden">
      <WorkspaceToolbar
        simState={simState} sessionId={sessionId} nodeCount={nodes.length}
        onStart={handleStart} onStop={handleStop} onWipe={handleWipe}
        onClear={handleClearCanvas} error={simError}
      />

      {/* Middle: palette + canvas + right panel */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <DevicePalette />

        {/* Canvas */}
        <div
          ref={canvasRef}
          className="flex-1 min-w-0 relative"
          onDragOver={onDragOver}
          onDrop={onDrop}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            onPaneClick={onPaneClick}
            onInit={(inst) => { rfInstanceRef.current = inst; }}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            deleteKeyCode={["Delete", "Backspace"]}
            nodesDraggable={true}
            nodesConnectable={true}
            elementsSelectable={true}
            selectNodesOnDrag={false}
            selectionOnDrag={false}
            panOnDrag={true}
            selectionMode={SelectionMode.Partial}
            fitView={nodes.length > 0}
            fitViewOptions={{ padding: 0.4 }}
            defaultEdgeOptions={{ type: "lab", data: { active: true } }}
            proOptions={{ hideAttribution: true }}
            style={{ background: "#ffffff" }}
          >
            <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#e8ecf0" />
            <Controls />
          </ReactFlow>

          {nodes.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 pointer-events-none select-none">
              <svg width="56" height="56" viewBox="0 0 56 56" fill="none" aria-hidden="true">
                <rect x="4" y="16" width="48" height="28" rx="5" stroke="#d0d7de" strokeWidth="2" strokeDasharray="4 3" />
                <circle cx="16" cy="30" r="4" fill="#d0d7de" />
                <circle cx="28" cy="30" r="4" fill="#d0d7de" />
                <circle cx="40" cy="30" r="4" fill="#d0d7de" />
              </svg>
              <p className="text-sm text-[#9198a1]">Drag devices from the left panel onto the canvas</p>
            </div>
          )}
        </div>

        {selectedNode && (
          <NodeSidePanel
            flowNode={selectedNode}
            topoNode={topoNode}
            topology={topology}
            tab={rightTab}
            onTabChange={setRightTab}
            simState={simState}
            onClose={() => setSelectedNode(null)}
            onOpenConfig={() => setConfigNode(selectedNode)}
          />
        )}
      </div>

      {/* Bottom panel — Terminal + Logs (CML style) */}
      <BottomPanel
        selectedNode={selectedNode}
        sessionId={sessionId}
        simState={simState}
        trace={trace}
        onTraceUpdate={setTrace}
      />

      {configNode && (
        <NodeConfigPopup
          node={configNode}
          onSave={saveConfig}
          onClose={() => setConfigNode(null)}
        />
      )}
    </div>
  );
}
