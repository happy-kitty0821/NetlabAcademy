"use client";

/**
 * /labs/workspace
 *
 * Cisco CML-style lab workspace. Single canvas, no extra steps.
 *
 * Layout:
 *  ┌──────────────────────────────────────────────────────┐
 *  │  Toolbar (lab name · Start/Stop/Wipe · status)        │
 *  ├──────┬───────────────────────────────────────────────┤
 *  │Left  │  Canvas (React Flow — drag, draw wires, click) │
 *  │panel │                                               │
 *  │      │                                 ┌─────────────┤
 *  │      │                                 │ Right panel │
 *  │      │                                 │ (on select) │
 *  └──────┴─────────────────────────────────┴─────────────┘
 *
 * User flow:
 *  1. Drag a device from the left panel onto the canvas.
 *  2. Draw a wire: hover a node until port handles appear, drag between them.
 *  3. Click a node to open the right panel (properties/interfaces/terminal).
 *  4. Click Start — simulation runs.  Click node → Terminal tab → open CLI.
 *  5. Right-click (or use toolbar) to wipe / reset.
 */

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

// ── Types ─────────────────────────────────────────────────────────────────────

export type SimState = "stopped" | "starting" | "running" | "stopping";

// ── Persistence ───────────────────────────────────────────────────────────────

const STORAGE_KEY = "netlab_canvas_v3";

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

// ── Default canvas (empty — user builds their own) ────────────────────────────

const EMPTY_NODES: DeviceNode[] = [];
const EMPTY_EDGES: Edge[] = [];

// ── Component ─────────────────────────────────────────────────────────────────

export default function WorkspacePage() {
  const saved = loadCanvas();
  if (saved?.nodes) bumpCounter(saved.nodes);

  const [nodes, setNodes, onNodesChange] = useNodesState<DeviceNode>(
    saved?.nodes ?? EMPTY_NODES,
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState(
    saved?.edges ?? EMPTY_EDGES,
  );

  // Persist on every change
  useEffect(() => { saveCanvas(nodes, edges); }, [nodes, edges]);

  // Re-stamp interface labels whenever nodes change (port counters shift)
  useEffect(() => {
    setEdges((eds) => stampEdgeLabels(nodes, eds));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes.length]);

  // ── Simulation state ───────────────────────────────────────────────────────
  const [simState,   setSimState]   = useState<SimState>("stopped");
  const [sessionId,  setSessionId]  = useState<string | null>(null);
  const [topology,   setTopology]   = useState<TopologyDocument | null>(null);
  const [simError,   setSimError]   = useState<string | null>(null);
  const [trace,      setTrace]      = useState<TraceEvent[]>([]);

  // ── Selection ──────────────────────────────────────────────────────────────
  const [selectedNode,  setSelectedNode]  = useState<DeviceNode | null>(null);
  const [configNode,    setConfigNode]    = useState<DeviceNode | null>(null);
  const [rightTab,      setRightTab]      = useState<"properties" | "interfaces" | "terminal">("properties");

  // ── React Flow instance (for drop positioning) ────────────────────────────
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rfInstanceRef = useRef<any>(null);
  const canvasRef     = useRef<HTMLDivElement>(null);

  // ── Wire connect ──────────────────────────────────────────────────────────
  const onConnect = useCallback((conn: Connection) => {
    setEdges((eds) => {
      const newEdges = addEdge(
        { ...conn, id: `e-${Date.now()}`, type: "lab", data: { active: true } },
        eds,
      );
      return stampEdgeLabels(nodes, newEdges);
    });
  }, [nodes, setEdges]);

  // ── Drag-drop from palette ────────────────────────────────────────────────
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const catalogId = e.dataTransfer.getData("application/netlab-device");
    if (!catalogId || !rfInstanceRef.current) return;

    const entry = DEFAULT_DEVICE_CATALOG.find((d) => d.id === catalogId);
    if (!entry) return;

    const bounds = canvasRef.current!.getBoundingClientRect();
    const position = rfInstanceRef.current.screenToFlowPosition({
      x: e.clientX - bounds.left,
      y: e.clientY - bounds.top,
    });

    const id = nextId();
    const count = nodes.filter((n) => n.data.catalogId === entry.id).length;
    const hostname =
      entry.icon === "pc"       ? `PC-${String.fromCharCode(65 + count)}`
      : entry.icon === "laptop" ? `Laptop-${count + 1}`
      : entry.icon === "server" ? `Server-${count + 1}`
      : entry.icon === "router" ? `R${count + 1}`
      : `SW${count + 1}`;

    const newNode: DeviceNode = {
      id,
      type: entry.id,
      position,
      data: {
        hostname,
        model:     entry.model,
        catalogId: entry.id,
        ip: entry.model === "host" ? "" : undefined,
      },
    };

    setNodes((nds) => [...nds, newNode]);
    // Open config popup immediately so user can set hostname/IP
    setConfigNode(newNode);
  }, [nodes, setNodes]);

  // ── Node click → open side panel ─────────────────────────────────────────
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    const dn = node as DeviceNode;
    setSelectedNode(dn);
    setRightTab("properties");
  }, []);

  // ── Node double-click → open terminal directly ────────────────────────────
  const onNodeDoubleClick = useCallback((_: React.MouseEvent, node: Node) => {
    const dn = node as DeviceNode;
    setSelectedNode(dn);
    if (simState === "running" && sessionId) {
      setRightTab("terminal");
    } else {
      setConfigNode(dn);
    }
  }, [simState, sessionId]);

  // ── Background click → deselect ───────────────────────────────────────────
  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // ── Save node config ──────────────────────────────────────────────────────
  const saveConfig = useCallback((id: string, patch: Partial<DeviceNodeData>) => {
    setNodes((nds) => nds.map((n) => n.id === id ? { ...n, data: { ...n.data, ...patch } } : n));
    setConfigNode(null);
  }, [setNodes]);

  // ── Delete selected node with Delete key (handled by ReactFlow) ───────────

  // ── Start simulation ──────────────────────────────────────────────────────
  const handleStart = useCallback(async () => {
    setSimError(null);
    setSimState("starting");
    setTrace([]);
    try {
      const result = convertFlowToTopology(nodes, edges);
      const topo   = result.topology;
      const session = await createSimulation(topo, 42);
      setTopology(topo);
      setSessionId(session.id);
      setSimState("running");
    } catch (err) {
      if (err instanceof TopologyValidationError) {
        setSimError(err.message);
      } else {
        const e = err as { error?: { message?: string } };
        setSimError(e?.error?.message ?? "Failed to start simulation.");
      }
      setSimState("stopped");
    }
  }, [nodes, edges]);

  // ── Stop ──────────────────────────────────────────────────────────────────
  const handleStop = useCallback(() => {
    setSimState("stopping");
    setTimeout(() => {
      setSimState("stopped");
      setSessionId(null);
      setTopology(null);
    }, 300);
  }, []);

  // ── Wipe ──────────────────────────────────────────────────────────────────
  const handleWipe = useCallback(async () => {
    if (sessionId) {
      try { await resetSimulation(sessionId); } catch { /* ignore */ }
    }
    setTrace([]);
    setSimState("stopped");
    setSessionId(null);
    setTopology(null);
    setSimError(null);
  }, [sessionId]);

  // ── Clear canvas ──────────────────────────────────────────────────────────
  const handleClearCanvas = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setSelectedNode(null);
    setConfigNode(null);
    sessionStorage.removeItem(STORAGE_KEY);
    handleWipe();
  }, [setNodes, setEdges, handleWipe]);

  // ── Trace update (from ping panel inside terminal) ────────────────────────
  const handleTraceUpdate = useCallback((newTrace: TraceEvent[]) => {
    setTrace(newTrace);
  }, []);

  // ── Find TopologyNode from FlowNode (for right panel) ─────────────────────
  const topoNode: TopologyNode | null = (() => {
    if (!selectedNode || !topology) return null;
    return topology.nodes.find((n) => n.id === selectedNode.id) ?? null;
  })();

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full bg-[#0d1117] overflow-hidden">

      {/* ── Toolbar ───────────────────────────────────────────────── */}
      <WorkspaceToolbar
        simState={simState}
        sessionId={sessionId}
        nodeCount={nodes.length}
        onStart={handleStart}
        onStop={handleStop}
        onWipe={handleWipe}
        onClear={handleClearCanvas}
        error={simError}
      />

      {/* ── Body ──────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Left: device palette */}
        <DevicePalette />

        {/* Center: canvas */}
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
            fitView
            fitViewOptions={{ padding: 0.4 }}
            defaultEdgeOptions={{ type: "lab", data: { active: true } }}
            proOptions={{ hideAttribution: true }}
            colorMode="dark"
            selectionOnDrag={false}
            panOnDrag={[1, 2]}
            selectionMode={SelectionMode.Partial}
            style={{
              background: "#1a1a2e",
              // Override React Flow CSS variables so the default node styles
              // (white bg, dark border, box-shadow selection) don't bleed through
              "--xy-node-background-color-default":    "transparent",
              "--xy-node-border-default":              "none",
              "--xy-node-boxshadow-hover-default":     "none",
              "--xy-node-boxshadow-selected-default":  "none",
              "--xy-node-border-radius-default":       "0",
              "--xy-handle-background-color-default":  "#00b4d8",
              "--xy-handle-border-color-default":      "#1a1a2e",
              "--xy-controls-button-background-color-default":       "#16213e",
              "--xy-controls-button-background-color-hover-default": "#0f3460",
              "--xy-controls-button-border-color-default":           "#0f3460",
              "--xy-controls-box-shadow-default":      "none",
            } as React.CSSProperties}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={28}
              size={1}
              color="#0f3460"
            />
            <Controls
              style={{
                background: "#161b22",
                border: "1px solid #21262d",
                borderRadius: 6,
              }}
            />
          </ReactFlow>

          {/* Empty state hint */}
          {nodes.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 pointer-events-none select-none">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden="true">
                <rect x="4" y="12" width="40" height="24" rx="4" stroke="#0f3460" strokeWidth="2" />
                <circle cx="12" cy="24" r="3" fill="#0f3460" />
                <circle cx="24" cy="24" r="3" fill="#0f3460" />
                <circle cx="36" cy="24" r="3" fill="#0f3460" />
              </svg>
              <p className="text-[13px] font-mono" style={{ color: "#0f3460" }}>Drag devices here to build your topology</p>
            </div>
          )}
        </div>

        {/* Right: node side panel (shows when a node is selected) */}
        {selectedNode && (
          <NodeSidePanel
            flowNode={selectedNode}
            topoNode={topoNode}
            topology={topology}
            tab={rightTab}
            onTabChange={setRightTab}
            sessionId={sessionId}
            simState={simState}
            trace={trace}
            onTraceUpdate={handleTraceUpdate}
            onClose={() => setSelectedNode(null)}
            onOpenConfig={() => setConfigNode(selectedNode)}
          />
        )}
      </div>

      {/* Config popup (appears on drop or double-click when stopped) */}
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
